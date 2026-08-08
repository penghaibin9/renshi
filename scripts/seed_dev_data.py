"""
一次性开发数据脚本：创建学校 + 管理员 + 少量教职工，供 HR01 本地演示。

用法（在 renshi 目录，必须用 exec 方式避免编码问题）：
  python manage.py shell -c "exec(open('scripts/seed_dev_data.py', encoding='utf-8').read())"
"""

from base.models import Company, Department, EmployeeType, JobPosition
from employee.models import Employee, EmployeeWorkInformation
from horilla_auth.models import HorillaUser

# ---- 学校（Company = A0 School/Tenant Root）----
company, _ = Company.objects.get_or_create(
    company="跃科测试大学",
    defaults={
        "hq": True,
        "address": "测试市科技园区",
        "country": "CN",
        "state": "测试省",
        "city": "测试市",
        "zip": "100000",
    },
)

# ---- 组织字典（两所学院）----
dept_info, _ = Department.objects.get_or_create(department="信息工程学院")
dept_info.company_id.add(company)
dept_biz, _ = Department.objects.get_or_create(department="经济管理学院")
dept_biz.company_id.add(company)
dept_arts, _ = Department.objects.get_or_create(department="人文艺术学院")
dept_arts.company_id.add(company)

pos_teacher, _ = JobPosition.objects.get_or_create(
    job_position="专任教师", department_id=dept_info
)
pos_teacher.company_id.add(company)
pos_admin, _ = JobPosition.objects.get_or_create(
    job_position="行政管理人员", department_id=dept_biz
)
pos_admin.company_id.add(company)
pos_counselor, _ = JobPosition.objects.get_or_create(
    job_position="辅导员", department_id=dept_arts
)
pos_counselor.company_id.add(company)

for t in ("专任教师", "行政管理人员", "辅导员", "实验技术人员", "工勤人员", "外聘教师"):
    et, _ = EmployeeType.objects.get_or_create(employee_type=t)
    et.company_id.add(company)

# ---- 管理员账号（必须关联 Employee + company，否则 CompanyMiddleware 会登出）----
admin, _ = HorillaUser.objects.get_or_create(
    username="hr_admin",
    defaults={
        "is_superuser": True,
        "is_staff": True,
        "email": "hr_admin@test.local",
    },
)
admin.set_password("Admin123!")
admin.is_superuser = True
admin.is_staff = True
admin.save()

admin_emp = Employee.objects.filter(employee_user_id=admin).first()
if not admin_emp:
    admin_emp = Employee.objects.create(
        employee_user_id=admin,
        employee_first_name="管理员",
        employee_last_name="张",
        email=admin.email,
        phone="13800000000",
        is_active=True,
    )
EmployeeWorkInformation.objects.filter(employee_id=admin_emp).update(
    company_id_id=company.pk,
    department_id_id=dept_biz.pk,
    job_position_id_id=pos_admin.pk,
)

# ---- 教职工（覆盖各学院/类型/性别/年龄）----
ROWS = [
    ("王", "明", "teacher1@test.local", "13800000001", dept_info, pos_teacher, "专任教师", "male", "1985-03-12"),
    ("李", "芳", "teacher2@test.local", "13800000002", dept_info, pos_teacher, "专任教师", "female", "1990-07-08"),
    ("张", "伟", "teacher3@test.local", "13800000003", dept_info, pos_teacher, "专任教师", "male", "1978-11-20"),
    ("刘", "静", "teacher4@test.local", "13800000004", dept_info, pos_teacher, "专任教师", "female", "1995-01-15"),
    ("陈", "强", "biz1@test.local", "13800000005", dept_biz, pos_admin, "行政管理人员", "male", "1988-09-01"),
    ("杨", "雪", "biz2@test.local", "13800000006", dept_biz, pos_admin, "行政管理人员", "female", "1992-05-25"),
    ("赵", "磊", "coun1@test.local", "13800000007", dept_arts, pos_counselor, "辅导员", "male", "1996-02-14"),
    ("孙", "丽", "coun2@test.local", "13800000008", dept_arts, pos_counselor, "辅导员", "female", "1993-08-30"),
    ("周", "刚", "tech1@test.local", "13800000009", dept_info, pos_teacher, "实验技术人员", "male", "1982-04-18"),
    ("吴", "敏", "ext1@test.local", "13800000010", dept_arts, pos_teacher, "外聘教师", "female", "1987-06-06"),
    ("郑", "涛", "ext2@test.local", "13800000011", dept_biz, pos_admin, "外聘教师", "male", "1991-12-02"),
    ("冯", "霞", "work1@test.local", "13800000012", dept_info, pos_teacher, "工勤人员", "female", "1975-10-10"),
]

for i, (first, last, email, phone, dept, pos, emp_type_name, gender, dob) in enumerate(ROWS, start=1):
    emp, created = Employee.objects.get_or_create(
        email=email,
        defaults={
            "employee_first_name": first,
            "employee_last_name": last,
            "phone": phone,
            "badge_id": f"T{i:04d}",
            "is_active": True,
            "gender": gender,
            "dob": dob,
        },
    )
    if created:
        EmployeeWorkInformation.objects.filter(employee_id=emp).update(
            company_id_id=company.pk,
            department_id_id=dept.pk,
            job_position_id_id=pos.pk,
            employee_type_id_id=EmployeeType.objects.get(employee_type=emp_type_name).pk,
            date_joining=f"2018-01-01",
        )

# 两名已离职员工（is_active=False，供"在岗"口径区分）
for i in (99, 98):
    email = f"left{i}@test.local"
    emp, created = Employee.objects.get_or_create(
        email=email,
        defaults={
            "employee_first_name": "离",
            "employee_last_name": f"职{i}",
            "phone": f"1390000{i:04d}",
            "badge_id": f"T{i:04d}",
            "is_active": False,
            "gender": "male",
            "dob": "1980-01-01",
        },
    )

print(f"school={company.id} {company.company}")
print(f"employees_active={Employee.objects.filter(is_active=True).count()}")
print(f"employees_total={Employee.objects.count()}")
print(f"admin={admin.username} / Admin123!")
