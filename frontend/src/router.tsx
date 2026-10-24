import { createBrowserRouter, Navigate, type RouteObject } from "react-router";

import { AppLayout } from "@/components/AppLayout";
import { JobPage } from "@/pages/JobPage";
import { JobsPage } from "@/pages/JobsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { UploadPage } from "@/pages/UploadPage";

/** The route table; shared with tests, which mount it in a memory router. */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/jobs" replace /> },
      { path: "upload", element: <UploadPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "jobs/:jobId", element: <JobPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
