import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TerraControl",
  description: "Costa Rica rainforest terrarium control"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
