#!/usr/bin/env bash
# Creates the AWS resources TierForge needs in LocalStack (currently: SQS queues).
# Local development only; in AWS the same queues are provisioned with Terraform.
# Safe to run more than once. Reads backend/.env via poe; falls back to LocalStack defaults.
set -euo pipefail

ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
REGION="${AWS_REGION:-us-east-1}"
QUEUE_URL_SETTING="${SQS_ENRICHMENT_QUEUE_URL:-http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/tierforge-enrichment}"
QUEUE="${QUEUE_URL_SETTING##*/}"  # the queue name is the last part of the URL
DLQ="${QUEUE}-dlq"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_PAGER=""

aws_local() { aws --endpoint-url "$ENDPOINT" --region "$REGION" "$@"; }

echo "Creating dead-letter queue '$DLQ'..."
DLQ_URL=$(aws_local sqs create-queue --queue-name "$DLQ" --query QueueUrl --output text)
DLQ_ARN=$(aws_local sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --query Attributes.QueueArn --output text)

echo "Creating queue '$QUEUE'..."
QUEUE_URL=$(aws_local sqs create-queue --queue-name "$QUEUE" --query QueueUrl --output text)

ATTRIBUTES_FILE=$(mktemp)
trap 'rm -f "$ATTRIBUTES_FILE"' EXIT
cat > "$ATTRIBUTES_FILE" <<JSON
{
  "VisibilityTimeout": "30",
  "ReceiveMessageWaitTimeSeconds": "20",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"$DLQ_ARN\",\"maxReceiveCount\":\"5\"}"
}
JSON
aws_local sqs set-queue-attributes --queue-url "$QUEUE_URL" --attributes "file://$ATTRIBUTES_FILE"

echo "Done:"
echo "  queue: $QUEUE_URL"
echo "  dlq:   $DLQ_URL"

if [ "$QUEUE_URL" != "$QUEUE_URL_SETTING" ]; then
  echo "Warning: SQS_ENRICHMENT_QUEUE_URL is $QUEUE_URL_SETTING" >&2
  echo "         but LocalStack returned $QUEUE_URL; update backend/.env to match." >&2
fi
