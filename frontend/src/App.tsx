import { RouterProvider } from "react-router";

import { Providers } from "./Providers";
import { createQueryClient } from "./queryClient";
import { router } from "./router";

const queryClient = createQueryClient();

export function App() {
  return (
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  );
}
