import Image, { type ImageLoader, type ImageProps } from "next/image";

const passthroughLoader: ImageLoader = ({ src }) => src;

function normalizeImageSrc(src: string): string {
  if (src.startsWith("//")) return `https:${src}`;
  if (src.startsWith("/") || /^(?:https?:|data:|blob:)/i.test(src)) return src;
  return `/${src.replace(/^\.?\//, "")}`;
}

function shouldBypassOptimization(src: string): boolean {
  return /^(?:https?:|data:|blob:)/i.test(src);
}

type AppImageProps = Omit<ImageProps, "src" | "loader"> & {
  src: string;
};

export default function AppImage({ src, alt, unoptimized, ...props }: AppImageProps) {
  const normalizedSrc = normalizeImageSrc(src);
  const bypassOptimization = shouldBypassOptimization(normalizedSrc);

  return (
    <Image
      {...props}
      src={normalizedSrc}
      alt={alt}
      loader={bypassOptimization ? passthroughLoader : undefined}
      unoptimized={unoptimized ?? bypassOptimization}
    />
  );
}