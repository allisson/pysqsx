.PHONY: test
test:
	poetry run pytest -v

.PHONY: lint
lint:
	poetry run pre-commit run --all-files

.PHONY: start-queue
start-queue:
	docker run --name pysqsx-elasticmq -p 9324:9324 -d softwaremill/elasticmq-native

.PHONY: stop-queue
stop-queue:
	docker kill $$(docker ps -aqf name=pysqsx-elasticmq)
	docker container rm $$(docker ps -aqf name=pysqsx-elasticmq)

.PHONY: clean
clean:
	@rm -rf dist/
	@rm -rf build/
	@rm -rf *.egg-info

.PHONY: dist
dist: clean
	poetry run python setup.py sdist
	poetry run python setup.py bdist_wheel

.PHONY: release
release: dist
	poetry run twine upload dist/*
