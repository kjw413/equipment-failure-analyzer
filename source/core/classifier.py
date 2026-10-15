from __future__ import annotations
import re, os, tempfile, shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from core.i18n import K
from core.models import UserError

REQUIRED_COLUMNS = ['id','enabled','priority','major','middle','minor','context','symptom','exclude']
# role: component = a named part; fallback = only when no part is named; override = cause statement.
RULE_COLUMNS = REQUIRED_COLUMNS + ['role']
ROLES = ('component','fallback','override')

DEFAULT_ENGINE = {
    # Max characters (spaces removed) between a part and its symptom in one clause.
    'window': 15,
    # Symptom words that report a part replacement or repair: the strongest evidence of the failed part.
    'replace_pattern': '교체|교환|신규|새것|a급|b급|수리|정비|재정비|가공|재가공',
    # Other repair words (adjust, inspect, clean) and adjusted attributes (위치, 타이밍).
    # A part that was only adjusted is weaker evidence than a stated failure.
    'action_pattern': '조정|재조정|조절|점검|청소|보수|용접|체결|고정|재조임|세팅|리셋|reset|재부팅|셧다운|온오프|재투입|'
                      '보강|수정|교정|calibration|영점|분해|조립|급유|도포|확인|제거|재가동|가동|조치|작업|'
                      '위치|각도|타이밍|원점|센터|높이|간격|텐션|감도|길이',
    # Worker-selected MES part code (비가동 코드(소)) -> compatible standard majors.
    'part_code_majors': {},
    # Choose the first stated failure when no clearer evidence exists. Off: such rows stay under review.
    'first_failure': False,
}

# Clause boundaries. Decimal points (1.3.5번) and hyphens inside codes (A-5, x-ray) are not boundaries.
CLAUSE_SPLIT = re.compile(r'[\n\r/;|*()\[\]→]|->|=>|>>|(?<!\d)\.|\.(?!\d)|\s-\s|(?<=[가-힣])-(?=[가-힣\s])')
NEGATION = re.compile(r'없|무(?![가-힣])')
# Parts listed together ('가이드 및 후크 조정') share the symptom; neither modifies the other.
LIST_JOIN = re.compile(r'(?:\d*번?)?(?:및|,|·|&|와|과|하고)(?:\d*번?)?')
# '…이탈로 인해 몰드 빠짐', '리크 발생하며 과동결': the stated failure caused what follows.
CAUSAL = re.compile(r'(?:발생)?(?:지|져|되|돼|해|하)?(?:(?:으로|로)(?:인해|인한|인하여)?|에의한|에의해|때문|어서|어|서|여|면서|며)')
# '스프라켓에서 이탈': a part followed by '에서' names a location, not the failed part.
LOCATIVE = re.compile(r'에서')
STRENGTH_REASON = {3:'교체 부품 우선',2:'교체 부품 우선',1:'고장 증상 우선',0:'고장 증상 우선'}

def validate_rules(rules: list[dict[str,Any]]) -> list[dict[str,Any]]:
    result, ids = [], set()
    for i, raw in enumerate(rules,2):
        row = {key: '' if raw.get(key) is None else str(raw.get(key)).strip() for key in RULE_COLUMNS}
        if not any(row[key] for key in REQUIRED_COLUMNS):
            continue
        if not row['id'] or row['id'] in ids:
            raise UserError(f'Rule row {i}: ID는 비어 있거나 중복될 수 없습니다.')
        ids.add(row['id'])
        if row['enabled'].casefold() not in ('0','1','true','false','yes','no'):
            raise UserError(f'Rule {row["id"]}: enabled는 0 또는 1입니다.')
        row['enabled'] = row['enabled'].casefold() in ('1','true','yes')
        try:
            row['priority'] = int(row['priority'])
        except ValueError as e:
            raise UserError(f'Rule {row["id"]}: priority는 정수입니다.') from e
        row['role'] = row['role'].casefold() or 'component'
        if row['role'] not in ROLES:
            raise UserError(f'Rule {row["id"]}: role은 {" / ".join(ROLES)} 중 하나입니다.')
        for key in ('major','middle','minor','context','symptom'):
            if not row[key]:
                raise UserError(f'Rule {row["id"]}: {key} 필수 입력')
        for key in ('context','symptom','exclude'):
            if len(row[key]) > 1000:
                raise UserError(f'Rule {row["id"]}: pattern 길이 초과')
            try:
                re.compile(row[key],re.IGNORECASE)
            except re.error as e:
                raise UserError(f'Rule {row["id"]}: {key} 정규식 오류: {e}') from e
        result.append(row)
    return result

def read_rules(path: Path) -> list[dict[str,Any]]:
    try:
        wb = openpyxl.load_workbook(path,read_only=True,data_only=True)
        try:
            ws = wb['rules'] if 'rules' in wb.sheetnames else wb.active
            it = ws.iter_rows(values_only=True)
            headers = [str(x or '').strip() for x in next(it,())]
            if not set(REQUIRED_COLUMNS).issubset(headers):
                raise UserError('classification_config.xlsx: 필수 열이 없습니다.')
            rows = [dict(zip(headers,row)) for row in it if any(v is not None for v in row)]
            return validate_rules(rows)
        finally:
            wb.close()
    except UserError:
        raise
    except Exception as e:
        raise UserError('classification_config.xlsx 파일을 확인하세요.') from e

def write_rules(path: Path, rules: list[dict[str,Any]]) -> None:
    checked = validate_rules(rules)
    wb=openpyxl.Workbook();ws=wb.active;ws.title='rules';ws.append(RULE_COLUMNS)
    for row in checked:
        ws.append([int(row[k]) if k=='enabled' else row[k] for k in RULE_COLUMNS])
    for cell in ws[1]:
        cell.font=Font(name='Malgun Gothic',bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid',fgColor='343A40')
    for col,width in zip('ABCDEFGHIJ',[22,10,10,14,22,34,55,65,40,12]):
        ws.column_dimensions[col].width=width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font=Font(name='Malgun Gothic',size=10)
            cell.alignment=Alignment(wrap_text=True,vertical='top')
            # A user-editable rule is data, never an Excel formula.
            if isinstance(cell.value,str) and cell.value.startswith('='):
                cell.data_type='s'
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(suffix='.xlsx',dir=path.parent);os.close(fd)
    try:
        wb.save(tmp)
        if path.exists():shutil.copy2(path,path.with_suffix('.xlsx.bak'))
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)

def clauses(text: str) -> list[str]:
    """Split a record into clauses and drop spaces, so '센서 교체' == '센서교체'."""
    return [part for part in (re.sub(r'\s+','',c) for c in CLAUSE_SPLIT.split(text or '')) if part]

@dataclass(frozen=True)
class Symptom:
    clause: int
    start: int
    end: int
    text: str
    kind: str  # R = replaced/repaired, A = adjusted/inspected, F = failure

@dataclass(frozen=True)
class Pair:
    """One named part (context) and the symptoms stated for it inside a clause."""
    rule: dict
    clause: int
    c0: int
    c1: int
    context: str
    symptoms: tuple

    @property
    def category(self):
        return (self.rule['major'],self.rule['middle'],self.rule['minor'])

    @property
    def first(self):
        return self.symptoms[0] if self.symptoms else None

    def kinds(self):
        return {s.kind for s in self.symptoms}

class RuleClassifier:
    """Deterministic, auditable part/symptom classification; no root-cause guessing.

    A rule matches only when its symptom follows its part inside the same clause,
    before the next named part. Competing rules are settled only by explicit,
    recorded evidence; otherwise the record stays under review with every
    candidate listed.
    """
    def __init__(self, rules: list[dict[str,Any]], engine: dict[str,Any] | None = None):
        self.engine={**DEFAULT_ENGINE,**(engine or {})}
        self.window=int(self.engine['window'])
        self.replace=re.compile(f'(?:{self.engine["replace_pattern"]})+',re.I)
        self.action=re.compile(f'(?:{self.engine["replace_pattern"]}|{self.engine["action_pattern"]})+',re.I)
        self.part_majors={re.sub(r'\s+','',str(k)):set(v) for k,v in (self.engine.get('part_code_majors') or {}).items()}
        self.rules=[]
        for row in sorted(validate_rules(rules),key=lambda r:(-r['priority'],r['id'])):
            if row['enabled']:
                symptom=None if row['symptom']=='.' else re.compile(row['symptom'],re.I)
                self.rules.append((row,re.compile(row['context'],re.I),symptom,
                                   re.compile(row['exclude'],re.I) if row['exclude'] else None))

    def kind(self, word: str) -> str:
        if self.replace.fullmatch(word):
            return 'R'
        return 'A' if self.action.fullmatch(word) else 'F'

    def symptoms(self, symptom, text: str, index: int, start: int, limit: int, nouns) -> list[Symptom]:
        words=[]
        for s in symptom.finditer(text,start,limit):
            # '이상 없음' is not a failure; '고정' inside the noun '고정볼트' is not a symptom.
            if not s.group() or NEGATION.match(text,s.end()):
                continue
            if any(a<=s.start() and s.end()<=b for a,b in nouns):
                continue
            words.append(Symptom(index,s.start(),s.end(),s.group(),self.kind(s.group())))
        return words

    def pairs(self, parts: list[str]) -> list[Pair]:
        found={}
        def add(rule,index,c,words):
            key=(rule['id'],index,c.start())
            old=found.get(key)
            found[key]=Pair(rule,index,c.start(),c.end(),c.group(),(old.symptoms if old else ())+tuple(words))
        previous=None
        for index,text in enumerate(parts):
            active=[(rule,context,symptom) for rule,context,symptom,exclude in self.rules
                    if not (exclude and exclude.search(text))]
            hits={rule['id']:[m for m in context.finditer(text) if m.group()] for rule,context,_ in active}
            # Part names only; fallback contexts are symptom words themselves (파손, 틀어짐).
            nouns=sorted((m.start(),m.end()) for rule,_,_ in active if rule['role']!='fallback' for m in hits[rule['id']])
            # A location ('스프라켓에서') does not end the previous part's statement.
            bounds=[(a,b) for a,b in nouns if not LOCATIVE.match(text,b)]
            last=None
            for rule,_,symptom in active:
                for c in hits[rule['id']]:
                    if symptom is None:
                        add(rule,index,c,())
                        continue
                    if LOCATIVE.match(text,c.end()):
                        continue
                    if rule['role']!='fallback' and (last is None or c.start()>last[2].start()):
                        last=(rule,symptom,c)
                    # A part's symptoms end where the next part begins, unless the two are listed together.
                    limit=min(c.end()+self.window,len(text))
                    for a,b in bounds:
                        if a>=c.end() and not LIST_JOIN.fullmatch(text[c.end():a]):
                            limit=min(limit,a)
                            break
                    words=self.symptoms(symptom,text,index,c.end(),limit,nouns)
                    if words:
                        add(rule,index,c,words)
            if nouns:
                previous=(index,last) if last else None
            elif previous:
                # '로드리스 실린더 파손/교체': a clause without a part continues the previous part.
                origin,(rule,symptom,c)=previous
                words=self.symptoms(symptom,text,index,0,len(text),())
                if words:
                    add(rule,origin,c,words)
        return list(found.values())

    def causal(self, pair: Pair, parts: list[str]) -> bool:
        """'…이탈로 인해 몰드 빠짐' links two failures; '고장으로 교체' is a self-contained repair."""
        for s in pair.symptoms:
            if s.kind!='F':
                continue
            text=parts[s.clause]
            marker=CAUSAL.match(text,s.end)
            if marker and marker.end()<len(text) and not self.action.match(text,marker.end()):
                return True
        return False

    def resolve(self, pairs: list[Pair], parts: list[str], part_code: str):
        """Return (pair, reason) or (None, '') when the evidence is not decisive."""
        def decided(live):
            return len({p.category for p in live})==1
        def best(live):
            return min(live,key=lambda p:(-p.rule['priority'],p.clause,p.c0,p.rule['id']))
        override=[p for p in pairs if p.rule['role']=='override']
        if override:
            return best(override),'원인 표현 규칙'
        live=list(pairs)
        if decided(live):
            return best(live),''
        components=[p for p in live if p.rule['role']=='component']
        if components and len(components)<len(live):
            live=components
            if decided(live):
                return best(live),'부품 규칙 우선'
        if all(p.rule['role']=='fallback' for p in live):
            return best(live),'부위 미기재 규칙 우선순위'
        # Two rules on the same part: the more specific (higher priority) rule refines it.
        same_part=defaultdict(list)
        for p in live:
            same_part[(p.clause,p.c0,p.c1)].append(p)
        live=[max(group,key=lambda p:(p.rule['priority'],p.rule['id'])) for group in same_part.values()]
        if decided(live):
            return best(live),'세부 규칙'
        # Overlapping part names on one symptom ('진공펌프' vs '펌프'): the longest, closest name wins.
        same_symptom=defaultdict(list)
        for p in live:
            if p.first:
                same_symptom[(p.first.clause,p.first.start)].append(p)
        losers=set()
        for group in same_symptom.values():
            head=max(group,key=lambda p:(p.clause,p.c1,p.c1-p.c0,p.rule['priority']))
            for p in group:
                listed=p.clause==head.clause and LIST_JOIN.fullmatch(parts[p.clause][p.c1:head.c0])
                if p is not head and p.category!=head.category and not listed:
                    losers.add(id(p))
        live=[p for p in live if id(p) not in losers]
        if decided(live):
            return best(live),'복합명사 중심어'
        # Evidence per category: replaced+failed > replaced > failed > only adjusted or inspected.
        kinds=defaultdict(set)
        for p in live:
            kinds[p.category]|=p.kinds()
        strength={category:3 if {'R','F'}<=k else 2 if 'R' in k else 1 if 'F' in k else 0 for category,k in kinds.items()}
        top=max(strength.values())
        tied=[p for p in live if strength[p.category]==top]
        if decided(tied):
            return best(tied),STRENGTH_REASON[top]
        causes=[p for p in tied if self.causal(p,parts)]
        if causes and decided(causes):
            return min(causes,key=lambda p:(p.clause,p.c0)),'원인 표현(으로/로 인해)'
        majors=self.part_majors.get(re.sub(r'\s+','',part_code or ''))
        if majors:
            fit=[p for p in tied if p.rule['major'] in majors]
            if fit and decided(fit):
                return best(fit),'MES 소분류 일치'
        if self.engine.get('first_failure'):
            failures=[p for p in tied if 'F' in p.kinds()] or tied
            return min(failures,key=lambda p:(p.clause,p.c0)),'첫 고장 기술'
        return None,''

    def classify(self, text: str, part_code: str = '') -> dict[str,str]:
        parts=clauses(text)
        pairs=self.pairs(parts)
        if not pairs:
            return {'major':K['unclassified'],'middle':K['unclassified'],'minor':K['unclassified'],
                    'status':K['unclassified'],'evidence':'','candidates':''}
        ordered=sorted(pairs,key=lambda p:(-p.rule['priority'],p.clause,p.c0))
        candidates=' | '.join(dict.fromkeys(f'{p.rule["id"]}: {p.rule["minor"]}' for p in ordered))
        chosen,reason=self.resolve(pairs,parts,part_code)
        status=K['auto']
        if chosen is None:
            chosen,status=ordered[0],K['review']
        words=', '.join(dict.fromkeys([chosen.context,*(s.text for s in chosen.symptoms[:2])]))
        evidence=f'{chosen.rule["id"]} | {words}'+(f' | {K["auto_resolved"]}: {reason}' if reason else '')
        return {**{k:chosen.rule[k] for k in ('major','middle','minor')},'status':status,
                'evidence':evidence,'candidates':candidates}
