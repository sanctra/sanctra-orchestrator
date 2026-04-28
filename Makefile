IMAGE=us-central1-docker.pkg.dev/memorial-prod/memorial-docker/memorial-orchestrator:dev
build:
	docker build -t $(IMAGE) .
push:
	docker push $(IMAGE)
run:
	docker run -p 8080:8080 $(IMAGE)
