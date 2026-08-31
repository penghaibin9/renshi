"""
hr_changes —— HR06 人事异动。

人事异动不是"修改员工当前字段"，而是一次有原因、有批准、有生效日、有前后事实、
有影响范围、可撤销/更正的正式人事事件。

权威边界（总册 §4）：
- HR06 负责"请求改变"（Case/Proposal/审批）；
- HR03（hr_staff）Service 负责"按有效日期写事实"；
- HR02（hr_structure）负责岗位占用/释放/预占；
- Legacy EmployeeWorkInformation 仅投影。
"""
