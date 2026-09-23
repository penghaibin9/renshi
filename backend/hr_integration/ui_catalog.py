"""Presentation metadata for the school Integration Hub UI.

This module does not define business authority or integration runtime behavior.
It only describes how the existing Adapter Registry should be presented to
school implementation staff.
"""
from __future__ import annotations

CATEGORY_UI = (
    {"code":"SSO","label":"统一认证","short":"CAS / OAuth2 / OIDC / LDAP","icon":"log-in-outline","priority":"P0","summary":"学校统一登录入口、账号身份与组织归属映射。"},
    {"code":"MASTER_DATA","label":"组织人员 / 主数据","short":"数据中台 / 主数据","icon":"people-outline","priority":"P0","summary":"组织、人员、岗位等权威基础数据交换。"},
    {"code":"RESEARCH","label":"科研","short":"项目 / 论文 / 成果","icon":"flask-outline","priority":"P1","summary":"科研成果与教师发展事实的来源适配。"},
    {"code":"ACADEMIC","label":"教务","short":"课程 / 教学工作量","icon":"school-outline","priority":"P1","summary":"课程、授课与教学工作量交换。"},
    {"code":"FINANCE","label":"财务","short":"支付 / 凭证 / 成本中心","icon":"wallet-outline","priority":"P0","summary":"工资支付、财务凭证与成本中心对接。"},
    {"code":"ATTENDANCE","label":"考勤","short":"门禁 / 一卡通 / 考勤机","icon":"time-outline","priority":"P1","summary":"考勤原始记录与门禁设备数据适配。"},
    {"code":"ESIGN","label":"电子签章","short":"合同 / 证明 / 签章","icon":"create-outline","priority":"P1","summary":"合同、证明和审批文件电子签署。"},
    {"code":"NOTIFICATION","label":"消息通知","short":"短信 / 邮件 / 企业微信","icon":"notifications-outline","priority":"P1","summary":"业务通知、验证码和待办消息送达。"},
)

# Fields are intentionally conservative: every key is already accepted by the
# V1.1 JSON contract. Optional fields remain optional until the runtime adapter
# consumes them.
ADAPTER_UI = {
    "SSO_CAS": {
        "title":"CAS 统一认证","badge":"高校常用","category":"SSO","protocol":"CAS 2.0 / 3.0",
        "summary":"适合学校已有统一身份认证平台，通过 CAS Login + Service Validate 完成单点登录。",
        "config_fields":[
            {"key":"login_path","label":"登录路径","placeholder":"/cas/login","help":"学校 CAS 登录入口相对路径。","required":True},
            {"key":"validate_path","label":"票据校验路径","placeholder":"/cas/serviceValidate","help":"建议优先使用 serviceValidate。","required":True},
            {"key":"logout_path","label":"退出路径","placeholder":"/cas/logout","help":"可选；用于统一退出。"},
            {"key":"service_parameter","label":"Service 参数名","placeholder":"service","help":"通常保持 service。"},
            {"key":"staff_no_claim","label":"工号属性","placeholder":"employeeNo","help":"如果 CAS 用户名本身就是工号，可填 user。","required":True},
            {"key":"allow_first_login_binding","label":"首次登录自动绑定","type":"select","options":[["0","关闭（推荐）"],["1","开启：仅在工号/账号/学校范围全部匹配时绑定"]],"default":"0"},
        ],
        "secret_fields":[],
        "materials":["CAS Server 根地址","登录 / 校验 / 退出路径","学校允许登记的业务系统 Service 地址规则","返回的工号、姓名、组织等属性说明"],
        "verification":"验证 CAS 登录端点可达；真实 Ticket 登录由统一认证运行时验收。",
    },
    "SSO_OAUTH2": {
        "title":"OAuth2 统一认证","badge":"标准协议","category":"SSO","protocol":"OAuth 2.0 Authorization Code",
        "summary":"适合学校统一认证平台提供 OAuth2 授权码模式。",
        "config_fields":[
            {"key":"authorize_path","label":"授权地址路径","placeholder":"/oauth/authorize","required":True},
            {"key":"token_path","label":"Token 地址路径","placeholder":"/oauth/token","required":True},
            {"key":"client_id","label":"Client ID","placeholder":"学校分配的 client_id","required":True},
            {"key":"userinfo_path","label":"用户信息路径","placeholder":"/oauth/userinfo","help":"运行时必须通过该接口取得受保护的用户身份。","required":True},
            {"key":"scope","label":"Scope","placeholder":"profile","help":"多个 scope 用空格分隔。"},
            {"key":"token_auth_method","label":"Token 客户端认证","type":"select","options":[["client_secret_post","client_secret_post（常用）"],["client_secret_basic","client_secret_basic"]],"default":"client_secret_post","help":"按学校 Token 端点要求选择。"},
            {"key":"subject_claim","label":"唯一身份字段","placeholder":"sub","help":"必须稳定且不会复用。","required":True},
            {"key":"staff_no_claim","label":"工号字段","placeholder":"employee_no","help":"用于匹配 HR03 工号。","required":True},
            {"key":"allow_first_login_binding","label":"首次登录自动绑定","type":"select","options":[["0","关闭（推荐）"],["1","开启：严格匹配后绑定"]],"default":"0"},
        ],
        "secret_fields":[{"key":"client_secret","label":"Client Secret","placeholder":"只写不回显","required":True}],
        "materials":["授权端点与 Token 端点","Client ID / Client Secret","回调地址登记规则","Scope 与用户信息字段说明"],
        "verification":"验证授权端点可达与配置完整性；正式登录需完成授权码回放。",
    },
    "SSO_OIDC": {
        "title":"OIDC 统一认证","badge":"推荐","category":"SSO","protocol":"OpenID Connect",
        "summary":"优先用于新建或标准化程度较高的学校认证平台，可利用 Discovery 元数据减少人工配置。",
        "config_fields":[
            {"key":"client_id","label":"Client ID","placeholder":"学校分配的 client_id","required":True},
            {"key":"discovery_path","label":"Discovery 路径","placeholder":"/.well-known/openid-configuration","default":"/.well-known/openid-configuration"},
            {"key":"scope","label":"Scope","placeholder":"openid profile email","default":"openid profile email"},
            {"key":"token_auth_method","label":"Token 客户端认证","type":"select","options":[["client_secret_post","client_secret_post（常用）"],["client_secret_basic","client_secret_basic"]],"default":"client_secret_post","help":"按学校 OIDC Provider 要求选择。"},
            {"key":"username_claim","label":"登录账号 Claim","placeholder":"preferred_username","help":"仅展示/诊断，不作为权限来源。"},
            {"key":"staff_no_claim","label":"工号 Claim","placeholder":"employee_no","help":"必须明确指定，用于匹配 HR03 工号。","required":True},
            {"key":"allow_first_login_binding","label":"首次登录自动绑定","type":"select","options":[["0","关闭（推荐）"],["1","开启：严格匹配后绑定"]],"default":"0"},
        ],
        "secret_fields":[{"key":"client_secret","label":"Client Secret","placeholder":"只写不回显","required":True}],
        "materials":["Issuer / Discovery 地址","Client ID / Client Secret","允许的 Redirect URI","Claims 字典（工号、姓名、组织、角色）"],
        "verification":"读取 OIDC Discovery 元数据并检查关键端点；正式登录需完成授权码 + ID Token 验证。",
    },
    "SSO_LDAP": {
        "title":"LDAP / LDAPS","badge":"目录认证","category":"SSO","protocol":"LDAP / LDAPS",
        "summary":"适合学校以 AD / LDAP 目录作为身份源，支持按 Base DN 与过滤器定位账号。",
        "config_fields":[
            {"key":"host","label":"LDAP 主机","placeholder":"ldap.example.edu.cn","required":True},
            {"key":"port","label":"端口","placeholder":"636","default":"636"},
            {"key":"base_dn","label":"Base DN","placeholder":"dc=example,dc=edu,dc=cn","required":True},
            {"key":"bind_dn","label":"Bind DN","placeholder":"cn=service,ou=system,dc=example,dc=edu,dc=cn"},
            {"key":"user_filter","label":"用户过滤器","placeholder":"(uid={username})","required":True},
            {"key":"username_attribute","label":"账号属性","placeholder":"uid","default":"uid"},
            {"key":"staff_no_attribute","label":"工号属性","placeholder":"employeeNumber","default":"employeeNumber","required":True},
            {"key":"allow_first_login_binding","label":"首次登录自动绑定","type":"select","options":[["0","关闭（推荐）"],["1","开启：严格匹配后绑定"]],"default":"0"},
            {"key":"security_mode","label":"安全模式","type":"select","options":[["LDAPS","LDAPS"],["STARTTLS","LDAP + StartTLS"],["PLAIN","LDAP（仅隔离测试）"]],"default":"LDAPS"},
        ],
        "secret_fields":[{"key":"bind_password","label":"Bind Password","placeholder":"只写不回显","required":True}],
        "materials":["LDAP/AD 主机与端口","Base DN / Bind DN","服务账号与密码","用户过滤器及工号、姓名、组织属性名"],
        "verification":"网页只做配置合同与白名单校验；真实 Bind/TLS 在部署验收门执行。",
    },
}

_HTTP_FAMILIES = {
    "MASTERDATA_HTTP_JSON": ("主数据 HTTP JSON","组织 / 人员 / 岗位","MASTER_DATA"),
    "RESEARCH_HTTP_JSON": ("科研 HTTP JSON","项目 / 论文 / 成果","RESEARCH"),
    "ACADEMIC_HTTP_JSON": ("教务 HTTP JSON","课程 / 教学工作量","ACADEMIC"),
    "FINANCE_HTTP_JSON": ("财务 HTTP JSON","工资支付 / 凭证 / 成本中心","FINANCE"),
    "ATTENDANCE_HTTP_JSON": ("考勤 HTTP JSON","门禁 / 一卡通 / 考勤机","ATTENDANCE"),
    "ESIGN_HTTP_JSON": ("电子签章 HTTP JSON","合同 / 证明 / 签章","ESIGN"),
    "SMS_HTTP": ("短信 HTTP","短信通知","NOTIFICATION"),
}
for code, (title, short, category) in _HTTP_FAMILIES.items():
    secret_key = "app_secret" if code == "ESIGN_HTTP_JSON" else "token"
    ADAPTER_UI[code] = {
        "title":title,"badge":"HTTP API","category":category,"protocol":"HTTPS + JSON",
        "summary":f"适配学校现有{short}接口，学校变化主要通过连接参数与字段映射消化。",
        "config_fields":[
            {"key":"health_path","label":"健康检查路径","placeholder":"/health","required":True},
            {"key":"api_prefix","label":"业务接口前缀","placeholder":"/api/v1","help":"可选；具体业务 Adapter 可继续细分。"},
        ],
        "secret_fields":[{"key":secret_key,"label":"访问密钥 / Token","placeholder":"只写不回显","required":True}],
        "materials":["接口 Base URL","健康检查地址","认证方式与访问密钥","接口字段字典与样例报文"],
        "verification":"从受控白名单网络发起真实 HTTP 探测并记录证据。",
    }

ADAPTER_UI["EMAIL_SMTP"] = {
    "title":"SMTP 邮件","badge":"SMTP","category":"NOTIFICATION","protocol":"SMTP / STARTTLS",
    "summary":"学校邮件服务器连接，用于通知、验证码及业务消息。",
    "config_fields":[
        {"key":"host","label":"SMTP 主机","placeholder":"smtp.example.edu.cn","required":True},
        {"key":"port","label":"端口","placeholder":"587","required":True,"default":"587"},
        {"key":"username","label":"用户名","placeholder":"hr@example.edu.cn","required":True},
        {"key":"security_mode","label":"安全模式","type":"select","options":[["STARTTLS","STARTTLS"],["SSL","SSL/TLS"],["PLAIN","无加密（仅隔离测试）"]],"default":"STARTTLS"},
    ],
    "secret_fields":[{"key":"password","label":"SMTP 密码","placeholder":"只写不回显","required":True}],
    "materials":["SMTP 主机和端口","发送账号","认证密码 / 授权码","TLS 要求与允许发件人规则"],
    "verification":"发起 SMTP NOOP 连通性检查；不发送真实邮件。",
}
ADAPTER_UI["WECOM"] = {
    "title":"企业微信","badge":"消息","category":"NOTIFICATION","protocol":"WeCom API",
    "summary":"将待办与通知发送到学校企业微信应用。",
    "config_fields":[
        {"key":"corp_id","label":"Corp ID","placeholder":"ww...","required":True},
        {"key":"agent_id","label":"Agent ID","placeholder":"1000001","required":True},
        {"key":"health_path","label":"探测路径","placeholder":"/cgi-bin/gettoken","required":True},
    ],
    "secret_fields":[{"key":"corp_secret","label":"Corp Secret","placeholder":"只写不回显","required":True}],
    "materials":["Corp ID","自建应用 Agent ID / Secret","可信 IP / 回调域名要求","成员账号映射规则"],
    "verification":"验证配置与受控网络可达性；消息发送由业务通知 Adapter 调用。",
}


def category_catalog():
    return CATEGORY_UI


def adapter_ui_catalog():
    return tuple({"code": code, **value} for code, value in ADAPTER_UI.items())


def get_adapter_ui(code: str):
    return ADAPTER_UI.get(str(code or "").strip().upper(), {})
