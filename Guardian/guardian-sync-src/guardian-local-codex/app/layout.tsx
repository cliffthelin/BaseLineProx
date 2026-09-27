import type { Metadata } from "next";
import "./globals.css";
export const metadata:Metadata={title:"Guardian — System Issue Center",description:"A calm, local issue center for understanding and validating Ubuntu system problems.",icons:{icon:"/favicon.svg",shortcut:"/favicon.svg"}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
