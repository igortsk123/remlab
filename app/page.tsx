export default function Home() {
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        textAlign: "center",
      }}
    >
      <div style={{ maxWidth: 640 }}>
        <p style={{ letterSpacing: 2, opacity: 0.6, fontSize: 13 }}>REMONT-LAB</p>
        <h1 style={{ fontSize: 34, lineHeight: 1.2, margin: "12px 0" }}>
          Обновите комнату с помощью AI
        </h1>
        <p style={{ opacity: 0.75, fontSize: 17 }}>
          Визуальная идея, товары, бюджет и план по фото. Каркас развёрнут —
          продуктовый flow (Stage&nbsp;1) в разработке.
        </p>
        <p style={{ marginTop: 28, fontSize: 13, opacity: 0.5 }}>
          bootstrap skeleton · {process.env.APP_VERSION ?? "dev"}
        </p>
      </div>
    </main>
  );
}
