import { Anchor, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

/** Any URL that doesn't match a page. */
export function NotFoundPage() {
  return (
    <Stack>
      <Title order={2}>Page not found</Title>
      <Text>
        <Anchor component={Link} to="/jobs">
          Go to the jobs list
        </Anchor>
      </Text>
    </Stack>
  );
}
