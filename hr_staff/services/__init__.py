"""
hr_staff.services —— HR03 服务层（总册 §19）。

原则：Selector 只读；Service 负责事务和不变量；API 不直接 .save()；
Projection Service 是唯一 authority → Horilla Employee 当前投影入口。
"""
