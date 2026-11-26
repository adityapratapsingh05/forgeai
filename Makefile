PYTHON ?= python3

.PHONY: test demo-hr demo-spares demo-unseen ui clean-cache

test:
	$(PYTHON) -m pytest -v

demo-hr:
	$(PYTHON) -m forgeai.factory \
		--brief demos/hr_policy/brief.txt \
		--docs demos/hr_policy/docs \
		--run-name hr_policy \
		--non-interactive \
		--eval-count 20 \
		--max-iters 1

demo-spares:
	$(PYTHON) -m forgeai.factory \
		--brief demos/ship_spares/brief.txt \
		--docs demos/ship_spares/docs \
		--run-name ship_spares \
		--non-interactive \
		--eval-count 20 \
		--max-iters 1

demo-unseen:
	@test -n "$(BRIEF)" || (echo "Usage: make demo-unseen BRIEF=... DOCS=... [RUN=unseen]" && exit 1)
	@test -n "$(DOCS)" || (echo "Usage: make demo-unseen BRIEF=... DOCS=... [RUN=unseen]" && exit 1)
	$(PYTHON) -m forgeai.factory \
		--brief "$(BRIEF)" \
		--docs "$(DOCS)" \
		--run-name "$(or $(RUN),unseen_run)" \
		--non-interactive

ui:
	$(PYTHON) -m streamlit run app/streamlit_app.py
