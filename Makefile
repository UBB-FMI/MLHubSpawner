REMOTE_USER := jupyterhub
REMOTE_HOST := 172.30.0.52
REMOTE_DIR := /home/jupyterhub/MLHubSpanwer
REMOTE := $(REMOTE_USER)@$(REMOTE_HOST)
ROOT_REMOTE := root@$(REMOTE_HOST)
SERVICE_NAME := jupyterhub
REMOTE_VENV := source /opt/tljh/hub/bin/activate
SSH := ssh -F /dev/null
RSYNC := rsync -e "$(SSH)"
RSYNC_FLAGS := -az --delete --exclude '.git/' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/'
UI_REVIEW_PYTHON ?= $(HOME)/Downloads/hf_model/venv/bin/python
UI_REVIEW_SCRIPT := scripts/review_ui.py
UI_REVIEW_SCREENSHOT_DIR ?= /tmp/mlhub-ui-review

.PHONY: all deploy sync install restart review-ui

all: deploy

deploy: sync
	$(SSH) $(REMOTE) "bash -lc '$(REMOTE_VENV) && cd $(REMOTE_DIR) && $(MAKE) install'"
	$(MAKE) restart

sync:
	$(SSH) $(REMOTE) 'mkdir -p $(REMOTE_DIR)'
	$(RSYNC) $(RSYNC_FLAGS) ./ $(REMOTE):$(REMOTE_DIR)/

install:
	pip uninstall mlspawner -y
	python3 setup.py install

restart:
	$(SSH) $(ROOT_REMOTE) 'systemctl restart $(SERVICE_NAME)'
	$(SSH) $(ROOT_REMOTE) 'systemctl is-active $(SERVICE_NAME)'

review-ui: deploy
	$(UI_REVIEW_PYTHON) $(UI_REVIEW_SCRIPT) --screenshot-dir $(UI_REVIEW_SCREENSHOT_DIR)
