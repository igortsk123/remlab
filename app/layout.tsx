import type { Metadata } from "next";
import type { ReactNode } from "react";
import Script from "next/script";
import { Inter } from "next/font/google";
import "./globals.css";

// Шрифт UUI; self-host на билде (без runtime-запросов к Google — важно для РФ).
// Токен --font-inter читает styles/uui/theme.css (--font-body).
const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-inter" });
import { Providers } from "@/components/Providers";
import { SiteHeader } from "@/components/SiteHeader";
import { VersionWatcher } from "@/components/VersionWatcher";
import { MetrikaPageviews } from "@/components/MetrikaPageviews";
import { METRIKA_COUNTER_ID } from "@/lib/metrika";

export const metadata: Metadata = {
  title: "remont-lab: ремонт своими руками, смета и материалы",
  description:
    "Помогаем сделать ремонт своими руками хорошо и недорого: калькуляторы материалов, список покупок и смета по ссылке.",
};

// Версия сборки, которой отдана страница (runtime env контейнера). Клиент сравнит её с /api/health
// и предложит обновиться после передеплоя (иначе серверные экшены форм молча ломаются).
const APP_VERSION = process.env.APP_VERSION ?? "dev";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <head>
        {/* Анти-FOUC масштаба (П4): применяем сохранённый data-font-scale ДО первой отрисовки. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var s=localStorage.getItem('remlab-font-scale');if(s==='L'||s==='XL'||s==='XXL'){document.documentElement.setAttribute('data-font-scale',s);}}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <Providers>
        <SiteHeader />
        {children}
        <footer className="container" style={{ paddingTop: 32, paddingBottom: 24 }}>
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            ИП Шубина Юлия Александровна · ОГРНИП 325420500121439 · ИНН 420221376189
          </p>
        </footer>
        </Providers>
        <VersionWatcher current={APP_VERSION} />
        <MetrikaPageviews />
        <Script id="yandex-metrika" strategy="afterInteractive">
          {`
            (function(m,e,t,r,i,k,a){
              m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
              m[i].l=1*new Date();
              for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}
              k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
            })(window,document,'script','https://mc.yandex.ru/metrika/tag.js?id=${METRIKA_COUNTER_ID}','ym');
            ym(${METRIKA_COUNTER_ID},'init',{ssr:true,webvisor:true,clickmap:true,accurateTrackBounce:true,trackLinks:true});
          `}
        </Script>
        <noscript>
          <div>
            <img src={`https://mc.yandex.ru/watch/${METRIKA_COUNTER_ID}`} style={{ position: "absolute", left: "-9999px" }} alt="" />
          </div>
        </noscript>
      </body>
    </html>
  );
}
