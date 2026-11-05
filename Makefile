# Основные команды управления проектом.

PYTHON  := .venv/Scripts/python.exe
PUML_OUT ?= docs/cdm/views/requirements_ontology.generated.puml
UI_HOST ?= 127.0.0.1
UI_PORT ?= 8000

.PHONY: diagram start stop test check db-up db-down db-reset clean seed wheel acceptance

# Параметры приёмочного прогона (scripts/acceptance_calculator.py).
CONFIRM ?= 0
LLM_MODE ?= cloud

# Генерация UML-диаграммы онтологии из Pydantic-модели.
diagram:
	$(PYTHON) scripts/ontology_to_puml.py -o $(PUML_OUT)

# Запуск тестов (pytest).
# Сценарии маркеров db/graph требуют поднятых хранилищ (make db-up).
ARGS ?= tests
test:
	$(PYTHON) -m pytest $(ARGS)

# Статический анализ контрактов и настроек (ruff + mypy).
# Зависимости: pip install -e ".[dev]"
check:
	$(PYTHON) -m ruff check contracts services/common/settings.py
	$(PYTHON) -m mypy contracts services/common/settings.py

# Шаблоны и промпты должны попасть в wheel как package resources.
wheel:
	$(PYTHON) -m build --wheel
	$(PYTHON) -c "import glob, zipfile; names = zipfile.ZipFile(glob.glob('dist/reqminer-*.whl')[0]).namelist(); print('\n'.join(n for n in names if 'templates/' in n or 'prompts/' in n))"

# Хранилища: PostgreSQL — Chunks и реестр, Neo4j — граф фактов.
# Доступ: DATABASE_URL и NEO4J_URI из .env, без них приложение работает на in-memory хранилищах.
db-up:
	docker compose up -d db graph

# Остановка хранилищ.
db-down:
	docker compose down

# Полный сброс хранилищ: контейнеры и volume удаляются, при следующем db-up схемы создаются заново.
db-reset:
	docker compose down -v

# Очистка данных в работающих хранилищах.
clean:
	$(PYTHON) scripts/db_clean.py

# Загрузка контрольного примера.
seed:
	$(PYTHON) scripts/seed_demo.py

# Полный приёмочный прогон на реальных PostgreSQL/Neo4j:
# Запуск: make acceptance CONFIRM=1
acceptance:
	$(PYTHON) scripts/acceptance_calculator.py $(if $(filter 1,$(CONFIRM)),--confirm) --llm-mode $(LLM_MODE) --keep-running --force

# Запуск веб-интерфейса.
start: stop
	$(PYTHON) -m uvicorn services.web_ui.app:app --host $(UI_HOST) --port $(UI_PORT) --reload

# Остановка веб-интерфейса, если он запущен.
stop:
	@$(PYTHON) scripts/ui_stop.py $(UI_PORT)
