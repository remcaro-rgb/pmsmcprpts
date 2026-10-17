export default function SignedOut() {
  return (
    <main className="mx-auto mt-[15vh] max-w-md px-4">
      <h1 className="text-xl font-semibold">You&apos;re signed out</h1>
      <p className="mt-2 text-stone-500">Close this tab, or sign in again to keep asking about your hotels.</p>
      <p className="mt-4">
        <a href="/auth/login" className="text-accent underline">Sign in again</a>
      </p>
    </main>
  );
}
