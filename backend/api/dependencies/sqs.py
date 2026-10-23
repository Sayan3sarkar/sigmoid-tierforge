from typing import Annotated

from fastapi import Depends, Request

from api.aws.sqs import SQSQueue


def get_sqs_queue(request: Request) -> SQSQueue:
    """The queue created in the app lifespan."""
    return request.app.state.sqs_queue


SQSQueueDep = Annotated[SQSQueue, Depends(get_sqs_queue)]
