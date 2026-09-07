export function EmailCard({ email }) {
  const when = email.date ? new Date(email.date).toLocaleDateString() : "";

  return (
    <div className="row">
      <div className="top">
        <span className="subj">{email.subject || "(no subject)"}</span>
        <span className="tag">{email.category || "unclassified"}</span>
      </div>
      <div className="meta">
        {email.sender_domain} · {when}
      </div>
      <div className="snip">{(email.snippet || "").slice(0, 160)}</div>
    </div>
  );
}
