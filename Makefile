.PHONY: help dev prod build stop logs logs-web shell clean db-shell status restart check test test-hr migrate makemessages compilemessages scheduler

COMPOSE ?= docker compose
COMPOSE_PROD ?= $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
I18N_EXCLUDES ?= --ignore=static/build/* --ignore=static/images/ionicons/*

help: ## 查看新手常用命令
	@echo '跃科高校人事系统常用命令:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

dev: ## 启动开发环境（Django + MySQL + Redis）
	$(COMPOSE) up --build

prod: ## 启动生产 overlay（需要 .env 强密钥）
	@test -f .env || (echo "缺少 .env：先 cp .env.dist .env 并替换所有 change-me" && exit 1)
	$(COMPOSE_PROD) up --build -d

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
	$(COMPOSE) exec db mysql -uhorilla_user -phorilla_pass horilla_db

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

test-hr: ## HR01~HR12 测试（MySQL）
	$(COMPOSE) run --rm web python manage.py test base hr_control_center hr_structure hr_staff hr_recruitment hr_onboarding hr_changes hr_external hr_qualification hr10_development hr_time hr_assessment --noinput --verbosity 1

scheduler: ## 单独启动 legacy employee scheduler；禁止随 web worker 自动启动
	$(COMPOSE) run --rm web python manage.py run_employee_scheduler

makemessages: ## 刷新翻译目录
	python manage.py makemessages -a $(I18N_EXCLUDES)

compilemessages: ## 编译 gettext
	python manage.py compilemessages

clean: ## 删除容器和卷（会丢失本地数据）
	$(COMPOSE_PROD) down -v
	docker system prune -f
