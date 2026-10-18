"use client";

import { fileUrl, type FileInfo } from "@/lib/chat";
import { useI18n } from "./I18n";

type FileKind = "xlsx" | "pptx" | "docx" | "pdf" | "png" | "other";

const TYPES: Record<string, { kind: FileKind; tint: string }> = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": { kind: "xlsx", tint: "bg-emerald-600" },
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": { kind: "pptx", tint: "bg-orange-600" },
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": { kind: "docx", tint: "bg-blue-600" },
  "application/pdf": { kind: "pdf", tint: "bg-red-600" },
  "image/png": { kind: "png", tint: "bg-stone-600" },
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function ArtifactCard({ file }: { file: FileInfo }) {
  const { t } = useI18n();
  const type = TYPES[file.mime] ?? { kind: "other", tint: "bg-stone-600" };
  const ext = type.kind === "other" ? "FILE" : type.kind.toUpperCase();
  return (
    <div
      className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white p-3 dark:border-stone-800 dark:bg-stone-900"
      data-testid="artifact"
    >
      <div
        className={`flex size-10 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold tracking-wide text-white ${type.tint}`}
        aria-hidden="true"
      >
        {ext}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{file.filename}</p>
        <p className="text-xs text-stone-500">
          {t.fileTypes[type.kind]} · {formatSize(file.size)}
        </p>
      </div>
      <a
        href={fileUrl(file)}
        download={file.filename}
        className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
      >
        {t.download}
      </a>
    </div>
  );
}
