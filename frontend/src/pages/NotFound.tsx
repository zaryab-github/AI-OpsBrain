import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted">That page does not exist, or it is not part of the modules installed on this platform.</p>
      <Link to="/" className="mt-4 inline-block text-sm text-brand underline">
        Back to the overview
      </Link>
    </div>
  );
}
