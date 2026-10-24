import { Group, Stack, Text } from '@mantine/core'
import { Dropzone, type FileRejection } from '@mantine/dropzone'

import classes from './CsvDropzone.module.css'

/** The API's own limit (UPLOAD_MAX_SIZE_BYTES). */
export const MAX_CSV_BYTES = 10 * 1024 * 1024

const CSV_TYPES = ['text/csv', 'application/vnd.ms-excel', '.csv']

interface Props {
  onFile: (file: File) => void
  onReject: (message: string) => void
  loading?: boolean
}

/** Drag-and-drop, or click to pick, one .csv file. */
export function CsvDropzone({ onFile, onReject, loading = false }: Props) {
  const handleReject = (rejections: FileRejection[]) => {
    const reason = rejections[0]?.errors[0]
    onReject(
      reason?.code === 'file-too-large'
        ? 'The file is larger than 10 MB.'
        : reason?.code === 'file-invalid-type'
          ? 'Upload a .csv file.'
          : (reason?.message ?? 'This file can’t be uploaded.'),
    )
  }

  return (
    <Dropzone
      onDrop={(files) => files[0] && onFile(files[0])}
      onReject={handleReject}
      accept={CSV_TYPES}
      maxSize={MAX_CSV_BYTES}
      maxFiles={1}
      multiple={false}
      loading={loading}
      className={classes.dropzone}
    >
      <Group justify="center" mih={160}>
        <Stack gap={4} align="center">
          <Text size="lg" fw={600}>
            Drop a store CSV here, or click to choose one
          </Text>
          <Text size="sm" c="dimmed">
            Columns: store_id, store_name, address, city, state, country. Up to 10 MB.
          </Text>
        </Stack>
      </Group>
    </Dropzone>
  )
}
