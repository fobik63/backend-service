export default function EditorPage() {
  return (
    <main className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border px-6 py-4">
        <h1 className="font-heading text-lg font-semibold tracking-tight">
          Editor
        </h1>
      </header>
      <section className="flex flex-1 items-center justify-center px-6 py-8">
        <p className="text-sm text-muted-foreground">
          Canvas-редактор карточек (заглушка).
        </p>
      </section>
    </main>
  );
}
