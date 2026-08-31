# 高校人事系统新手本地开发总控

## 只认这一份正式代码

正式主程序目录：

```text
F:\高校人事系统\01_项目源码\高校人事系统主程序
```

不要再打开历史克隆、旧 worktree 或备份目录开发。备份只用于恢复，正式修改全部在上面的目录进行。

## 文件夹怎么认

```text
backend/    后端：Django、数据库模型、接口、HR01～HR18 业务模块
frontend/   前端：HTML 模板、CSS、JavaScript、图片
deploy/     部署：Docker、Nginx、Gunicorn
docs/       文档：说明书、模块施工册、验收记录
tests/      测试：自动测试、视觉测试、基线和测试产物
scripts/    工具：检查、数据准备、浏览器验收
.runtime/   本机运行数据：数据库、上传文件、静态收集文件
```

仓库根目录只保留常用入口文件，例如 `manage.py`、`requirements.txt`、`Dockerfile` 和 `docker-compose.yml`。

## 每天固定五步

```powershell
# 1. 进入唯一主程序
Set-Location 'F:\高校人事系统\01_项目源码\高校人事系统主程序'

# 2. 查看当前修改
git status --short --branch

# 3. 检查目录和 Django
python scripts/check_hr18_structure.py
python manage.py check

# 4. 一次只修改一个模块并运行该模块测试
python manage.py test hr_changes --keepdb --noinput

# 5. 查看差异，确认后再提交
git diff --stat
```

也可以直接双击 `F:\高校人事系统\03_启动工具\1_启动人事系统.cmd` 启动本地 Docker 系统。

## 前端在哪里

公共 V2 页面和资源统一放在：

```text
frontend/templates/        公共 HTML 模板
frontend/static/hr/        高校人事 V2 的 CSS、JavaScript、图标
backend/hr_xxx/templates/  某个 HR 模块自己的 Django 模板
```

整理目录只改变文件所在位置，没有改变浏览器里的 `/static/...` 地址，也没有删除已重构的 V2 页面。

## 后端在哪里

所有 Django app 都在 `backend/`。例如：

```text
backend/horilla/             全局配置、URL、启动入口
backend/hr_control_center/   HR01
backend/hr_changes/          HR06
backend/hr_data/             HR18
```

日常命令仍在仓库根目录执行 `python manage.py ...`，不需要先进入 `backend/`。

## 不要做的事

- 不要删除 `backend/` 里的 Horilla 目录；它们仍是当前系统的一部分。
- 不要把 `.runtime/` 提交到 Git；这里是本机数据库和上传文件。
- 不要在 `99_备份归档` 里继续开发。
- 不要用 `git reset --hard`、强制推送或批量删除来“清理”。
- 不要因为整理目录而改 Django app 名称；app 名称关联数据库迁移历史。

HR01～HR18 的业务入口见 [`modules/README.md`](modules/README.md)。
