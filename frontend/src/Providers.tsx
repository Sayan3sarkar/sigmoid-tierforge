import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { theme } from "./theme";

interface Props {
  queryClient: QueryClient;
  children: ReactNode;
}

/** Everything the app needs around it; tests wrap pages in the same providers. */
export function Providers({ queryClient, children }: Props) {
  return (
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}
