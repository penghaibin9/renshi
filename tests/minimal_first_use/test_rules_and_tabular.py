"""Executable non-Django tests: these do NOT claim database acceptance."""
from pathlib import Path
import importlib.util
import io
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[2]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

policy = load('first_use_policy', 'backend/base/first_use_policy.py')
tab = load('import_tabular', 'backend/hr_staff/import_tabular.py')
identity = load('legacy_identity', 'backend/horilla_auth/legacy_identity.py')

BASE = dict(company_name='验收学校', first_name='管理员', email='school@example.edu.cn')

def test_minimal_bootstrap_real_blanks():
    values = policy.normalize_bootstrap_options(BASE)
    assert values['username'] == BASE['email']
    assert all(values[k] == '' for k in policy.OPTIONAL_PROFILE_FIELDS)

@pytest.mark.parametrize('field',['company_name','first_name','email'])
def test_missing_required(field):
    with pytest.raises(policy.BootstrapInputError): policy.normalize_bootstrap_options({**BASE, field:' '})

@pytest.mark.parametrize('field,value', [('company_name','x'*51),('username','Horilla Bot'),('phone','\x00'),('email','x'*151+'@example.com')])
def test_invalid_bootstrap(field,value):
    with pytest.raises(policy.BootstrapInputError): policy.normalize_bootstrap_options({**BASE,field:value})

@pytest.mark.parametrize('facts,state',[
    ({},'BLOCKED'),
    ({'scope_ok':True,'school_count':1},'NEEDS_ORGANIZATION'),
    ({'scope_ok':True,'school_count':1,'organization_ready':True},'NEEDS_STAFF'),
    ({'scope_ok':True,'school_count':1,'organization_ready':True,'staff_ready':True},'NEEDS_ROLES'),
    ({'scope_ok':True,'school_count':1,'organization_ready':True,'staff_ready':True,'roles_ready':True},'BASIC_DATA_READY')])
def test_server_fact_state_never_production(facts,state):
    result=policy.first_use_progress(facts)
    assert result['state']==state and result['production_accepted'] is False


def test_csv_header_whitespace_and_source_rows():
    rows=tab.read_import_rows(' 姓名 , 所属部门 \n\n张老师,数学系\n'.encode(),'staff.csv')
    assert rows==[{'legal_name':'张老师','department_name':'数学系','_source_row_no':3}]

@pytest.mark.parametrize('content',[
    '姓名,legal_name\n张,李\n','姓名,foo\n张,x\n','姓名\n张,多余列\n','姓名\n',
    '姓名\n"未闭合\n','工号\n0001\n','姓名\n\x00\n'])
def test_bad_csv_rejected(content):
    with pytest.raises(tab.TabularError):tab.read_import_rows(content.encode(),'staff.csv')


def test_xlsx_real_template_has_no_fake_people():
    raw=(ROOT/'backend/hr_staff/resources/staff_import_template.xlsx').read_bytes()
    with pytest.raises(tab.TabularError, match='模板只有表头'):tab.read_import_rows(raw,'template.xlsx')


def xlsx_mutation(sheet_xml=None, extra=None):
    raw=(ROOT/'backend/hr_staff/resources/staff_import_template.xlsx').read_bytes()
    original=zipfile.ZipFile(io.BytesIO(raw)); out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for info in original.infolist():
            data=original.read(info.filename)
            if sheet_xml and info.filename=='xl/worksheets/sheet1.xml': data=sheet_xml.encode()
            z.writestr(info.filename,data)
        if extra: z.writestr(*extra)
    return out.getvalue()


def sheet(data,header='姓名'):
    return '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'+header+'</t></is></c></row>'+data+'</sheetData></worksheet>'


def test_xlsx_actual_literal_values_source_row():
    xml=sheet('<row r="4"><c r="A4" t="inlineStr"><is><t>张老师</t></is></c></row>')
    assert tab.read_import_rows(xlsx_mutation(xml),'x.xlsx')==[{'legal_name':'张老师','_source_row_no':4}]

@pytest.mark.parametrize('data',[
    '<row r="2"><c r="A2"><f>1+1</f><v>2</v></c></row>',
    '<row r="2"><c r="A2" t="e"><v>#REF!</v></c></row>',
    '<row r="2"><c r="A3" t="inlineStr"><is><t>x</t></is></c></row>',
    '<row r="2"><c r="A2" t="s"><v>-1</v></c></row>',
    '<row r="6002"><c r="A6002" t="str"><v>x</v></c></row>',
])
def test_unsafe_cells_rejected(data):
    with pytest.raises(tab.TabularError): tab.read_import_rows(xlsx_mutation(sheet(data)),'x.xlsx')

@pytest.mark.parametrize('entry',[
    ('xl/vbaProject.bin',b'macro'),('../outside',b'x'),
    ('xl/externalLinks/externalLink1.xml',b'<x/>'),
    ('xl/_rels/untrusted.rels',b'<Relationships><Relationship TargetMode="External" Target="https://example.org"/></Relationships>'),
    ('xl/_rels/bad.rels',b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'),
])
def test_zip_security(entry):
    with pytest.raises(tab.TabularError):tab.read_import_rows(xlsx_mutation(extra=entry),'x.xlsx')


def test_numeric_identity_rejected_before_precision_loss():
    xml=sheet('<row r="2"><c r="A2" t="inlineStr"><is><t>某老师</t></is></c><c r="B2"><v>123456789012345678</v></c></row>')
    xml=xml.replace('</row><row r="2">','<c r="B1" t="inlineStr"><is><t>证件号码</t></is></c></row><row r="2">',1)
    with pytest.raises(tab.TabularError,match='必须设为文本'):tab.read_import_rows(xlsx_mutation(xml),'x.xlsx')

@pytest.mark.parametrize('value,epoch,expected',[('1',False,'1900-01-01'),('61',False,'1900-03-01'),('0',True,'1904-01-01')])
def test_excel_dates(value,epoch,expected):assert tab._excel_date(value,epoch,2)==expected

@pytest.mark.parametrize('v',['60','nan','inf','-1','9.5','999999999'])
def test_bad_excel_dates(v):
    with pytest.raises(tab.TabularError):tab._excel_date(v,False,2)


def account(**kwargs): return dict(id=7,username='staff',password='hash-not-plain',is_active=True,is_staff=False,is_superuser=False,**kwargs)

def test_legacy_new_and_exact_only():
    a=account()
    assert identity.migration_action(a,None,None)=='CREATE'
    assert identity.migration_action(a,a,a)=='EXACT_EXISTING'

@pytest.mark.parametrize('change',[{'id':8},{'username':'other'},{'password':'different'},{'is_superuser':True},{'is_active':False}])
def test_legacy_conflicts_no_merge(change):
    a=account(); b={**a,**change}
    with pytest.raises(identity.LegacyIdentityConflict):identity.migration_action(a,b,b)


def test_limits():
    with pytest.raises(tab.TabularError):tab.read_import_rows(b'x'*(tab.MAX_BYTES+1),'x.csv')
    with pytest.raises(tab.TabularError):tab.read_import_rows(('姓名\n'+'张\n'*5001).encode(),'x.csv')
    with pytest.raises(tab.TabularError):tab.read_import_rows(b'x','x.xlsm')
