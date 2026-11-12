import Image from "next/image";

// Forkcast mark: a fork inside a light bulb (source file: Forkcast.png at the repo root).
export function LogoMark({ className = "size-9" }: { className?: string }) {
  return <Image src="/brand/forkcast.png" alt="" width={256} height={256} aria-hidden className={`${className} rounded-[28%]`} />;
}
