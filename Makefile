.PHONY: final-source-gate procurement-performance help dev prod prod-preflight acceptance-qa acceptance-plan go-live-audit handover-export handover-verify build stop logs logs-web shell clean db-shell status restart check test test-hr migrate makemessages compilemessages scheduler

COMPOSE ?= docker compose
COMPOSE_PROD ?= $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
I18N_EXCLUDES ?= --ignore=frontend/static/build/* --ignore=frontend/static/images/ionicons/*

help: ## 查看新手常用命令
	@echo '跃科高校人事系统常用命令:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

dev: ## 启动开发环境（Django + MySQL + Redis）
	$(COMPOSE) up --build

prod-preflight: ## 校验 Docker Compose 版本和生产 overlay
	@COMPOSE_COMMAND="$(COMPOSE)" python scripts/check_prod_compose.py

prod: prod-preflight ## 启动生产 overlay（需要 .env 强密钥）
	@test -f .env || (echo "缺少 .env：先 cp .env.dist .env 并替换所有 change-me" && exit 1)
	$(COMPOSE_PROD) up --build -d

acceptance-plan: ## 只查看隔离验收门禁步骤，不启动容器
	python scripts/run_hr_acceptance_gate.py --plan

acceptance-qa: ## 独立 QA 项目执行 HR01~HR18 生产形态验收，绝不读取正式 .env
	python scripts/run_hr_acceptance_gate.py

go-live-audit: prod-preflight ## 正式开流量前只读体检；示例 make go-live-audit TENANT_ID=1001
	@test -n "$(TENANT_ID)" || (echo "缺少 TENANT_ID，例如 make go-live-audit TENANT_ID=1001" && exit 1)
	@test -f .env || (echo "缺少 .env：上线体检必须使用正式候选配置" && exit 1)
	$(COMPOSE_PROD) run --rm web python manage.py hr_go_live_audit --tenant "$(TENANT_ID)" --strict

handover-export: prod-preflight ## 生成学校开放格式移交包；需 RECIPIENT/PURPOSE/OPERATOR
	@test -n "$(RECIPIENT)" || (echo "缺少 RECIPIENT：学校接收部门/单位" && exit 1)
	@test -n "$(PURPOSE)" || (echo "缺少 PURPOSE：例如 合同到期数据移交" && exit 1)
	@test -n "$(OPERATOR)" || (echo "缺少 OPERATOR：实际操作人" && exit 1)
	$(COMPOSE_PROD) exec -T backup-scheduler python manage.py create_school_handover_package \
	  --recipient "$(RECIPIENT)" --purpose "$(PURPOSE)" --operator "$(OPERATOR)" \
	  --confirm-sensitive-export I_UNDERSTAND_THIS_EXPORT_CONTAINS_SENSITIVE_HR_DATA

handover-verify: prod-preflight ## 校验学校移交包；需 PACKAGE/OPERATOR
	@test -n "$(PACKAGE)" || (echo "缺少 PACKAGE：移交包 tar.gz 文件名" && exit 1)
	@test -n "$(OPERATOR)" || (echo "缺少 OPERATOR：实际校验人" && exit 1)
	$(COMPOSE_PROD) exec -T backup-scheduler python manage.py verify_school_handover_package \
	  "$(PACKAGE)" --operator "$(OPERATOR)"

build: ## 构建镜像
	$(COMPOSE) build

stop: ## 停止服务
	$(COMPOSE_PROD) down

logs: ## 查看全部日志
	$(COMPOSE) logs -f

logs-web: ## 只看 Django/Gunicorn 日志
	$(COMPOSE) logs -f web

shell: ## 进入 web 容器
	$(COMPOSE) exec web bash

db-shell: ## 打开 MySQL 控制台
	$(COMPOSE) exec db mysql -urenshi_user -prenshi_pass renshi_db

status: ## 查看容器状态
	$(COMPOSE) ps

restart: ## 重启服务
	$(COMPOSE) restart

migrate: ## 执行 MySQL migration + consistency check
	$(COMPOSE) run --rm web sh -c 'python manage.py makemigrations --check --dry-run && python manage.py migrate --noinput && python manage.py migrate --check'

check: ## Django system check
	$(COMPOSE) run --rm web python manage.py check

test: ## 全仓 Django 测试（MySQL）
	$(COMPOSE) run --rm web python manage.py test --noinput --verbosity 1

test-hr: ## HR01~HR18 全模块测试（MySQL）
	$(COMPOSE) run --rm web python manage.py test base hr_control_center hr_structure hr_staff hr_recruitment hr_onboarding hr_changes hr_contracts hr_external hr_qualification hr10_development hr_time hr_assessment hr_title hr_appointment hr_payroll hr_exit hr_self hr_data --noinput --verbosity 1

scheduler: ## 单独启动 legacy employee scheduler；禁止随 web worker 自动启动
	$(COMPOSE) run --rm web python manage.py run_employee_scheduler

makemessages: ## 刷新翻译目录
	python manage.py makemessages -a $(I18N_EXCLUDES)

compilemessages: ## 编译 gettext
	python manage.py compilemessages

clean: ## 删除容器和卷（会丢失本地数据）
	$(COMPOSE_PROD) down -v
	docker system prune -f

final-source-gate: ## 最终采购级纯源码门禁（不冒充真实 MySQL/学校验收）
	python scripts/check_hr10_import_contract.py
	python scripts/check_hr10_staff_identity_contract.py
	python scripts/check_hr18_procurement_sync_contract.py
	python scripts/check_school_handover_contract.py
	python scripts/check_final_procurement_contract.py
	python -m unittest discover -s tests/final_acceptance -p 'test_*.py' -v

procurement-performance: ## QA 性能门；需 NORMAL_URL/ANALYTICS_URL，显式产生并发负载
	python scripts/run_procurement_performance_probe.py --allow-load --normal-url "$(NORMAL_URL)" --analytics-url "$(ANALYTICS_URL)" --concurrency 100 --requests-per-url 100 --output-json "$(or $(OUTPUT_JSON),procurement-performance-evidence.json)"
