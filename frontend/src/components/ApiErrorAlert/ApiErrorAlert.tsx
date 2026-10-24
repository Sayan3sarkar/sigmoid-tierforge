import { Alert, List } from "@mantine/core";

import type { ApiError } from "@/api/errors";

interface Props {
  error: ApiError;
  title?: string;
  /** Hide problems tied to a form field when the form shows them itself. */
  hideFieldErrors?: boolean;
}

/** An API error's detail, and each problem the API listed. */
export function ApiErrorAlert({
  error,
  title = "Something went wrong",
  hideFieldErrors = false,
}: Props) {
  const problems = error.errors
    .filter((item) => !(hideFieldErrors && item.field))
    .map((item) =>
      item.field ? `${item.field}: ${item.message}` : item.message,
    );

  return (
    <Alert color="red" title={title} role="alert">
      {error.detail}
      {problems.length > 0 && (
        <List size="sm" mt="xs">
          {problems.map((problem) => (
            <List.Item key={problem}>{problem}</List.Item>
          ))}
        </List>
      )}
    </Alert>
  );
}
