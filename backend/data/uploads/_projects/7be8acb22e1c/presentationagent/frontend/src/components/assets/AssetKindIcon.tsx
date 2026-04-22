import {
  Code2,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Presentation,
  Puzzle,
  Workflow,
} from "lucide-react";

import { resolveAssetKind, type AssetDisplayKind, type AssetTypeDescriptor } from "@/lib/assetTypes";

interface AssetKindIconProps {
  kind?: AssetDisplayKind;
  item?: AssetTypeDescriptor;
  className?: string;
}

export function AssetKindIcon({ kind, item, className }: AssetKindIconProps) {
  const resolvedKind = kind || resolveAssetKind(item || {});
  const cls = className || "w-5 h-5";

  switch (resolvedKind) {
    case "ppt":
      return <Presentation className={`${cls} text-orange-500`} />;
    case "document":
      return <FileText className={`${cls} text-blue-500`} />;
    case "code":
      return <Code2 className={`${cls} text-green-500`} />;
    case "image":
      return <ImageIcon className={`${cls} text-fuchsia-500`} />;
    case "drawio":
      return <Workflow className={`${cls} text-cyan-500`} />;
    case "skill":
      return <Puzzle className={`${cls} text-violet-500`} />;
    default:
      return <FolderOpen className={`${cls} text-gray-400`} />;
  }
}