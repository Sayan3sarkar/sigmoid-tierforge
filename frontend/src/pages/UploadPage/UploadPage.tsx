import { Alert, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiErrorAlert } from "@/components/ApiErrorAlert";
import { CsvDropzone } from "@/components/CsvDropzone";
import { useUploadStores } from "@/hooks/useUploadStores";
import { Format } from "@/utils/format";

/** Upload a store CSV; on success, go to the new job. */
export function UploadPage() {
  const navigate = useNavigate();
  const upload = useUploadStores();
  const [rejection, setRejection] = useState<string | null>(null);

  const handleFile = (file: File) => {
    setRejection(null);
    upload.mutate(file, {
      onSuccess: (result) => {
        notifications.show({
          color: "teal",
          title: "Upload accepted",
          message: `${Format.integer(result.row_count)} stores saved; enrichment started.`,
        });
        void navigate(`/jobs/${result.job_id}`);
      },
    });
  };

  return (
    <Stack gap="lg" maw={760}>
      <div>
        <Title order={2}>Upload stores</Title>
        <Text c="dimmed">
          Every row is checked first. If any row is invalid, nothing is saved
          and every problem is listed.
        </Text>
      </div>

      <CsvDropzone
        onFile={handleFile}
        onReject={setRejection}
        loading={upload.isPending}
      />

      {rejection && (
        <Alert color="red" title="File not accepted" role="alert">
          {rejection}
        </Alert>
      )}
      {upload.error && (
        <ApiErrorAlert error={upload.error} title="Upload rejected" />
      )}
    </Stack>
  );
}
