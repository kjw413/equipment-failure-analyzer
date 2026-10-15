from __future__ import annotations
import json, logging, os, shutil, sys, tempfile, hashlib
from pathlib import Path
from datetime import datetime
from typing import Any
from version import APP_ID
from core.models import UserError

CONFIG_FILES = ['settings.json','column_mapping.json','normalization.json',
                'equipment_aliases.json','product_aliases.json','equipment_families.json',
                'classification_config.xlsx','equipment_names.json','final_report.json']

def resource_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]

def app_root() -> Path:
    """The folder the user started the program from: the EXE's folder, or the project folder."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]

def writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix='.efa_write_test_', dir=path)
        os.close(handle);Path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False

def output_root() -> Path:
    """Default report folder: ./output next to the program. Falls back to the user
    data folder when the program folder is read-only (e.g. an EXE under Program Files)."""
    custom = os.environ.get('EFA_OUTPUT_DIR')
    preferred = Path(custom).expanduser().resolve() if custom else app_root()/'output'
    if writable_dir(preferred):
        return preferred
    fallback = user_root()/'output'
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

def user_root() -> Path:
    custom = os.environ.get('EFA_DATA_DIR')
    if custom:
        return Path(custom).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / APP_ID
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / APP_ID

def atomic_json(path: Path, value: Any, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))
    handle, name = tempfile.mkstemp(prefix=path.stem+'_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

class ConfigStore:
    """Defaults are copied once. User rules and corrections survive upgrades."""
    def __init__(self, directory: Path | None = None):
        self.root = Path(directory) if directory else user_root()
        self.config_dir = self.root / 'config'
        self.log_dir = self.root / 'logs'
        for p in (self.config_dir,self.log_dir):
            p.mkdir(parents=True,exist_ok=True)
        for name in CONFIG_FILES:
            dest = self.config_dir/name
            if not dest.exists():
                shutil.copy2(resource_root()/'config'/name,dest)
        self.override_path = self.config_dir/'manual_overrides.json'
        if not self.override_path.exists():
            atomic_json(self.override_path, {}, backup=False)
        self.mapping_path = self.config_dir/'column_overrides.json'
        # Bring untouched defaults up to this release; the user's own edits are kept.
        from core.defaults_merge import merge_defaults
        try:
            self.merge_summary = merge_defaults(resource_root()/'config', self.config_dir)
        except Exception:
            logging.getLogger(__name__).exception('Defaults merge failed')
            self.merge_summary = {}
        # Keep pre-v1.5.0 programs from reading these rules with their old engine (see classifier.write_rules).
        from core.classifier import upgrade_rules_format
        try:
            if upgrade_rules_format(self.config_dir/'classification_config.xlsx'):
                self.merge_summary.setdefault('rules',{})['format_upgraded'] = 1
        except Exception:
            logging.getLogger(__name__).exception('Rules format upgrade failed')

    def read(self, name: str) -> Any:
        try:
            return json.loads((self.config_dir/name).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as e:
            raise UserError(f'\uc124\uc815 \ud30c\uc77c \ud655\uc778: {name}\n{e}') from e

    def load(self) -> dict[str, Any]:
        from core.classifier import read_rules
        result = {Path(n).stem:self.read(n) for n in CONFIG_FILES if n.endswith('.json')}
        from core.equipment_names import validate_names
        final_report = result['final_report']
        if not isinstance(final_report, dict) or final_report.get('schema_version') != 1:
            raise UserError('final_report.json: unsupported schema')
        names = result['equipment_names']
        if not isinstance(names, dict) or names.get('schema_version') != 1:
            raise UserError('equipment_names.json: unsupported schema')
        names['mappings'] = validate_names(names.get('mappings', {}))
        sections = result['settings'].get('report_sections', [])
        result['settings']['report_sections'] = [key for key in sections if key != 'product']
        if 'equipment_types' not in result['settings']['report_sections']:
            result['settings']['report_sections'].append('equipment_types')
        result['settings'].setdefault('donut_top_n', 5)
        result['rules'] = read_rules(self.config_dir/'classification_config.xlsx')
        result['overrides'] = self.read('manual_overrides.json')
        payload = json.dumps(result,ensure_ascii=False,sort_keys=True).encode('utf-8')
        result['hash'] = hashlib.sha256(payload).hexdigest()
        return result

    def save_override(self, event_id: str, values: dict[str,str]) -> None:
        overrides = self.read('manual_overrides.json')
        overrides[event_id] = {**overrides.get(event_id,{}),**{k:v for k,v in values.items() if v not in (None,'')},'saved_at':datetime.now().isoformat(timespec='seconds')}
        atomic_json(self.override_path, overrides)

    def override(self, event_id: str) -> dict[str,str]:
        return dict(self.read('manual_overrides.json').get(event_id,{}))

    def update_override(self, event_id: str, patch: dict[str,str | None]) -> dict[str,str]:
        """Set (text) or remove (None) individual corrected fields of one record."""
        overrides = self.read('manual_overrides.json')
        current = {k:v for k,v in overrides.get(event_id,{}).items() if k!='saved_at'}
        for key,value in patch.items():
            if value is None or str(value).strip()=='':
                current.pop(key,None)
            else:
                current[key] = str(value).strip()
        if current:
            overrides[event_id] = {**current,'saved_at':datetime.now().isoformat(timespec='seconds')}
        else:
            overrides.pop(event_id,None)
        atomic_json(self.override_path, overrides)
        return current

    def clear_override(self, event_id: str) -> None:
        self.update_override(event_id, {key:None for key in self.override(event_id)})

    def rekey_overrides(self, moves: dict[str,str]) -> int:
        """Copy corrections to new record IDs after a column re-mapping. Old keys are kept."""
        overrides = self.read('manual_overrides.json')
        moved = 0
        for old,new in moves.items():
            if old!=new and old in overrides and new not in overrides:
                overrides[new] = dict(overrides[old]);moved += 1
        if moved:
            atomic_json(self.override_path, overrides)
        return moved

    @staticmethod
    def header_signature(headers: list[str]) -> str:
        return hashlib.sha256(json.dumps(list(headers),ensure_ascii=False).encode('utf-8')).hexdigest()[:16]

    def saved_mapping(self, headers: list[str]) -> dict[str,str | None] | None:
        """The column mapping the user last confirmed for a sheet with these exact headers."""
        if not self.mapping_path.exists():
            return None
        entry = self.read(self.mapping_path.name).get(self.header_signature(headers))
        return dict(entry['mapping']) if entry else None

    def save_mapping(self, headers: list[str], mapping: dict[str,str | None]) -> None:
        saved = self.read(self.mapping_path.name) if self.mapping_path.exists() else {}
        saved[self.header_signature(headers)] = {'headers':list(headers),'mapping':dict(mapping),
                                                 'saved_at':datetime.now().isoformat(timespec='seconds')}
        atomic_json(self.mapping_path, saved)

    def save_equipment_names(self, mapping: dict[str, str]) -> dict:
        """Save one canonical current mapping; settings survive restart/upgrades."""
        from core.equipment_names import validate_names
        checked = validate_names(mapping)
        current = self.read('equipment_names.json')
        if current.get('mappings') == checked:
            return current
        value = {'schema_version': 1,
                 'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                 'mappings': checked}
        atomic_json(self.config_dir / 'equipment_names.json', value)
        return value

    def save_report_settings(self, fields: dict[str, str]) -> None:
        value = self.read('final_report.json')
        limits = {'title': 100, 'department': 120, 'prepared_by': 80, 'closing_note': 1600}
        for key, limit in limits.items():
            if key in fields:
                text = str(fields[key]).strip()
                if len(text) > limit:
                    raise UserError(f'{key}: maximum {limit} characters')
                value[key] = text
        atomic_json(self.config_dir / 'final_report.json', value)
