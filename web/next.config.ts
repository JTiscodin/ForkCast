import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // a stray pnpm-workspace.yaml in the home dir made Turbopack pick the wrong root
  // (and fail to resolve deps like gsap); pin it to this app
  turbopack: { root: __dirname },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "media-assets.swiggy.com",
        pathname: "/**",
      },
      {
        protocol: "https",
        hostname: "res.cloudinary.com",
        pathname: "/**",
      },
    ],
  },
};

export default nextConfig;
