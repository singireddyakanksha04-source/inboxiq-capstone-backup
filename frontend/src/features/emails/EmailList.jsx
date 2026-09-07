import { EmailCard } from "./EmailCard.jsx";

export function EmailList({ emails }) {
  return (
    <div>
      {emails.map((email) => (
        <EmailCard key={email.id} email={email} />
      ))}
    </div>
  );
}
