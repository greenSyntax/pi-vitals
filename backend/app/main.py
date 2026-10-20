from fastapi import FastAPI

app = FastAPI(title="Pi-Vitals", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
