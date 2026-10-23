from pydantic import BaseModel


class EnrichmentMessage(BaseModel):
    """Body of an enrichment SQS message: one store to enrich within one job.

    Provisional: the fields will follow the data model once it is settled.
    """

    job_id: int
    store_id: str
