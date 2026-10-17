import { fileUrl, type FileInfo } from "@/lib/chat";

const TYPES: Record<string, { label: string; ext: string; tint: string }> = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
    label: "Excel workbook", ext: "XLSX", tint: "bg-emerald-600",
  },
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
    label: "PowerPoint deck", ext: "PPTX", tint: "bg-orange-600",
  },
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
    label: "Word document", ext: "DOCX", tint: "bg-blue-600",
  },
  "application/pdf": { label: "PDF document", ext: "PDF", tint: "bg-red-600" },
  "image/png": { label: "PNG image", ext: "PNG", tint: "bg-stone-600" },
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function ArtifactCard({ file }: { file: FileInfo }) {
  const type = TYPES[file.mime] ?? { label: "File", ext: "FILE", tint: "bg-stone-600" };
  return (
    <div
      className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white p-3 dark:border-stone-800 dark:bg-stone-900"
      data-testid="artifact"
    >
      <div
        className={`flex size-10 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold tracking-wide text-white ${type.tint}`}
        aria-hidden="true"
      >
        {type.ext}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{file.filename}</p>
        <p className="text-xs text-stone-500">
          {type.label} · {formatSize(file.size)}
        </p>
      </div>
      <a
        href={fileUrl(file)}
        download={file.filename}
        className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
      >
        Download
      </a>
    </div>
  );
}
