"use client";

import { useState } from "react";
import Image from "next/image";
import { cn } from "@/lib/utils";
import { dishInitials } from "./dish-helpers";

/**
 * Robust dish image with graceful fallback.
 *
 * Why not a plain next/image:
 *  - Swiggy CDN URLs often end in ".jpg_compressed" / ".png_compressed" and can
 *    return content the next/image optimizer rejects with
 *    "url is valid but upstream response is invalid". We therefore render them
 *    `unoptimized` (browser fetches the CDN directly — which works fine) and
 *    normalize obviously-broken URLs.
 *  - Any load error (403, dead asset, non-image) falls back to a neutral
 *    muted tile with the dish initials instead of a broken-image icon.
 */
export function DishImage({
  src,
  alt,
  sizes,
  className,
  fallbackClassName,
  rounded = "rounded-md",
}: {
  src?: string | null;
  alt: string;
  sizes?: string;
  className?: string;
  fallbackClassName?: string;
  rounded?: string;
}) {
  const normalized = normalizeSwiggyUrl(src);
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(normalized) && !failed;

  if (!showImage) {
    return (
      <div
        aria-hidden
        className={cn(
          "flex size-full items-center justify-center bg-muted text-muted-foreground",
          rounded,
          fallbackClassName
        )}
      >
        <span className="text-[0.7em] font-semibold tracking-wide">
          {dishInitials(alt)}
        </span>
      </div>
    );
  }

  return (
    <Image
      src={normalized as string}
      alt={alt}
      fill
      sizes={sizes}
      unoptimized
      onError={() => setFailed(true)}
      className={cn("object-cover", rounded, className)}
    />
  );
}

/** Return a usable https URL or null. Guards against relative / bare-id values. */
function normalizeSwiggyUrl(src?: string | null): string | null {
  if (!src) return null;
  const s = src.trim();
  if (!s) return null;
  if (s.startsWith("http://") || s.startsWith("https://")) return s;
  // Some responses give only a Cloudinary image id/path — build the CDN URL.
  if (/^[\w/\-.]+$/.test(s)) {
    return `https://media-assets.swiggy.com/swiggy/image/upload/${s}`;
  }
  return null;
}

export default DishImage;
