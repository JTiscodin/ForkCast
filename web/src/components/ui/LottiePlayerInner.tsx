"use client";

import * as React from "react";
import { Lottie } from "lottie-react";
import type { LottieHandle } from "lottie-react";

/**
 * Internal module that actually evaluates lottie-react. It exists only so
 * `LottiePlayer` can load it through `next/dynamic({ ssr: false })` — this
 * Next version only permits `ssr: false` inside client components, and this
 * file is never imported statically anywhere.
 */
export interface LottiePlayerInnerProps {
  src: string | object;
  loop: boolean;
  autoplay: boolean;
  speed?: number;
  className?: string;
  /** Imperative handle sink so the wrapper can play/pause (e.g. offscreen). */
  handleRef?: React.MutableRefObject<LottieHandle | null>;
}

export default function LottiePlayerInner({
  src,
  loop,
  autoplay,
  speed,
  className,
  handleRef,
}: LottiePlayerInnerProps) {
  return (
    <Lottie
      src={src}
      loop={loop}
      autoplay={autoplay}
      speed={speed}
      className={className}
      lottieRef={(handle) => {
        if (handleRef) handleRef.current = handle;
      }}
    />
  );
}
