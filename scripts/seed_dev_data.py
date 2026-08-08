"""
一次性开发数据脚本：创建学校 + 少量员工，供 HR01 本地端到端验证。

用法（在 renshi 目录）：
  python manage.py shell < scripts/seed_dev_data.py
"""

from base.models import Company, Department, EmployeeType, JobPosition
from django.contrib.auth.models import Permission
from employee.models import Employee, EmployeeWorkInformation
from horilla_auth.models import HorillaUser
from horilla.horilla_middlewares import set_selected_company

# ---- 学校（Company = A0 School/Tenant Root）----
company, _ = Company.objects.get_or_create(
    company="测试大学", defaults={"hq": True, "address": "测试市", "country": "CN", "state": "XX", "city": "测试市", "zip": "000000"}
)

# ---- 组织字典 ----
dept, _ = Department.objects.get_or_create(department="计算机学院")
dept.company_id.add(company)

pos, _ = JobPosition.objects.get_or_create(job_position="专任教师", department_id=dept)
pos.company_id.add(company)

emp_type, _ = EmployeeType.objects.get_or_create(employee_type="专任教师")
emp_type.company_id.add(company)

# ---- 管理员账号 ----
admin, _ = HorillaUser.objects.get_or_create(
    username="hr_admin",
    defaults={"is_superuser": True, "is_staff": True, "email": "hr_admin@test.local"},
)
admin.set_password("Admin123!")
admin.is_superuser = True
admin.is_staff = True
admin.save()

# ---- 员工（显式指定 company）----
set_selected_company(company.id)

for i in range(1, 6):
    first = f"张{i}" if i % 2 else f"李{i}"
    emp, created = Employee.objects.get_or_create(
        email=f"teacher{i}@test.local",
        defaults={
            "employee_first_name": first,
            "employee_last_name": f"测试{i}",
            "phone": f"1380000{i:04d}",
            "badge_id": f"T{i:04d}",
            "is_active": True,
            "gender": "male" if i % 2 else "female",
            "dob": f"198{i}-0{i}-1{i}" if i <= 4 else "1990-05-20",
        },
    )
    if created:
        wi = emp.employee_work_info
        wi.company_id = company
        wi.department_id = dept
        wi.job_position_id = pos
        wi.employee_type_id = emp_type
        wi.date_joining = f"202{i}-0{i}-1{i}"
        wi.save()

print(f"school={company.id} employees={Employee.objects.count()} admin={admin.username}")
