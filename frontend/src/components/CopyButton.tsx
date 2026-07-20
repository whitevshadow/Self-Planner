"use client";

import { useState } from "react";

/** One-click copy with a brief "Copied ✓" confirmation. */
export default function CopyButton({
  text,
  label = "Copy",
  className = "mini ghost",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (e.g. non-secure context) — nothing to do */
    }
  }

  return (
    <button type="button" className={className} onClick={copy}>
      {copied ? "Copied ✓" : label}
    </button>
  );
}
