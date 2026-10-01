test:
	pytest -q

run:
	python -m src.run_all --config configs/experiment.yaml

docker:
	docker compose up --build research

figures: run
