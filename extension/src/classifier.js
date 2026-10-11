// The rule classifier, ported line for line from the backend's
// services/classifier.py so a message lands in the same mailbox here as it
// does in the dashboard. Keyword/header heuristics only: no model call, no
// network, nothing leaves the browser.
//
// Input shape mirrors models/email.py: { subject, snippet, body_text, labels,
// sender, sender_domain }.
(function (InboxIQ) {
  var CATEGORIES = ["promotion", "receipt", "bill", "newsletter", "shipping", "otp",
    "subscription", "alert", "security", "personal", "other"];

  // Codes and account-safety mail. Checked before everything else, even
  // Gmail's Personal label, because a reset code from a sender Gmail files as
  // personal is still a code.
  var URGENT_RULES = [
    // Payment problems, transfers and status notices. First, because bank
    // templates carry bill words ("autopay") in every footer.
    ["alert",
      "\\bzelle\\b|couldn[’']?t (complete|process) your (online )?payment|" +
      "payment (failed|declined|was declined|was unsuccessful|could not be processed)|" +
      "\\btracked (flight|price)s?\\b|price (alert|tracking)|" +
      "application (received|submitted)|thank you for (applying|your application)|" +
      "registration status"],
    ["otp",
      "\\b(one[- ]time (pass)?code|verification code|temporary (access )?code|" +
      "(password )?reset code|security code|log-?in code|sign-?in code|" +
      "otp|\\b\\d{6}\\b is your)\\b"],
    ["security",
      "\\b(new device|new sign-?in|signed in (to|from)|verify it'?s you|" +
      "security alert|suspicious (login|activity)|shared (your|some).*data|" +
      "account access|someone (used|is using) your|" +
      "password (was |has been )?(successfully )?(reset|changed|updated)|reset your password|" +
      "confirm (this |recent |your )?activity|fraud alert|unusual activity)\\b"],
  ];

  var PROMO_PATTERN =
    "(\\b\\d{1,2}% off\\b|sale ends|limited time|\\bdeals?\\b|coupon|promo code|" +
    "shop now|save big|\\bclearance\\b|\\bsave (today|now)\\b|for \\$0(\\.00)?\\b|" +
    "\\b\\d+ months? of \\w+( \\w+)? for (free|\\$0)|" +
    "try (\\w+ )?premium|save up to|only \\d+ \\w+ left|fees? waived)";

  var BILL_PATTERN =
    "\\b(payment due|amount due|statement is (now )?(ready|available)|" +
    "autopay|past due|minimum payment|(new|your) invoice|" +
    "invoice (is )?(available|attached|due|#))\\b";

  var RULES = [
    // Needs a parcel/order in the sentence: a bare "delivered" or "arriving"
    // also shows up in car ads ("new inventory arriving") and product news.
    ["shipping",
      "\\b(out for delivery|tracking (number|id|#|info\\w*|link)|" +
      "track (your )?(package|order|shipment|parcel|delivery)|" +
      "(package|order|shipment|parcel|item)s? (has |have |was |were |is |are )?" +
      "(been )?(shipped|delivered|on (its|the) way|arriving|out for delivery)|" +
      "(has|have) shipped|delivery (update|attempt|exception)|" +
      "arriving (today|tomorrow|on (mon|tue|wed|thu|fri|sat|sun)))\\b"],
    ["receipt", "\\b(receipt|order confirm(ed|ation)?|your order|thanks for your (order|purchase)|invoice paid)\\b"],
    ["bill", BILL_PATTERN],
    // Lifecycle of a subscription the user already has. Plain "membership" or
    // "annual subscription" is also sales copy and fine print on deal mail.
    ["subscription",
      "\\b(renews? (on|automatically|soon|in \\d+ days)|auto-?renew(al|s|ed)? (on|is|will|notice)|" +
      "renewal (date|notice|reminder|confirmation)|" +
      "(your )?(free )?trial (ends|is ending|will end|expires|has ended|ending soon)|" +
      "billing cycle|next billing date|" +
      "(your|the) (plan|subscription|membership) (has been |was |is |will be |will )?" +
      "(renewed|renews|cancell?ed|expired|expires|expiring|ending|ends|paused|" +
      "activated|confirmed|started)|" +
      "plan will (renew|end|expire|change)|" +
      "subscription (confirmation|receipt|renewal|cancell?ation|has been)|" +
      "subscription is (now )?(ready|active))\\b"],
    ["alert",
      "\\b(new listing|price drop|saved search|search alert|top match|" +
      "job match(es)?|new job(s)? for you|now hiring|recommended for you|" +
      "based on your (recent )?(activity|search))\\b"],
    ["promotion", PROMO_PATTERN],
    ["newsletter",
      "\\b(newsletter|this week in|digest|unsubscribe from our list|issue #|" +
      "weekly (\\w+ )?(news|roundup|recap))\\b"],
  ];

  // A payment receipt for something that recurs (a plan, a membership, a
  // billing period) is a subscription, not a one-off receipt. Both halves
  // must match: "total charged" alone is a ride or an order, and
  // "subscription" alone is sales copy.
  var PAID_RE = new RegExp(
    "\\b(receipt|amount paid|total charged|invoice (has been )?paid|has been paid|" +
    "payment (received|successful|confirmation|was successful|has been processed)|" +
    "thanks for your payment|(we|you('ve| have)? been|you were) (charged|billed))\\b");
  var RECURRING_RE = new RegExp(
    "\\b((monthly|annual|yearly) (plan|subscription|membership|fee|billing|charge)|" +
    "per (month|year)|recurring|auto-?renew\\w*|renews?|" +
    "billed (monthly|annually|yearly|every)|next (billing|payment|charge)|" +
    "billing (period|cycle)|subscription|membership)\\b" +
    "|\\$\\d[\\d,.]*\\s?/\\s?(mo|month|yr|year)\\b");
  // "Sep 3 - Oct 3, 2026" or "09/03/2026 - 10/03/2026": the period a charge covers.
  var MON = "(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?";
  var PERIOD_RANGE_RE = new RegExp(
    "\\b" + MON + " (\\d{1,2})(?:,? (\\d{4}))?\\s*(?:-|–|—|to)\\s*" + MON + " (\\d{1,2}),? (\\d{4})\\b" +
    "|\\b(\\d{1,2})/(\\d{1,2})/(\\d{4})\\s*(?:-|–|—|to)\\s*(\\d{1,2})/(\\d{1,2})/(\\d{4})\\b", "i");

  function isRecurringCharge(text) {
    return PAID_RE.test(text) && (RECURRING_RE.test(text) || PERIOD_RANGE_RE.test(text));
  }

  // Account notices and event confirmations. Only used when nothing above
  // matched and Gmail did not file the mail under Promotions, since the same
  // words ("webinar", "account") are common in marketing.
  var NOTICE_RULES = [
    ["alert",
      "\\b(available balance|balance (is )?(below|above)|daily (account )?summary|" +
      "zelle|contact information (change|update)|you received a new (letter|document|message)|" +
      "direct deposit|(large|new) (purchase|transaction)|account alert)\\b"],
    ["alert",
      "\\b(registration (is )?confirmed|you'?re registered|" +
      "confirm your (spot|seat|registration|application)|webinar|webclass|" +
      "event reminder|meetup|rsvp)\\b"],
  ];

  // Shipping words from these senders are car/home listings ("new inventory
  // arriving", "price drop"), never a parcel.
  var LISTING_DOMAINS = ["realtor.com", "zillow.com", "cars.com", "carfax.com", "imotors.com",
    "autotrader.com", "cargurus.com", "carvana.com", "truecar.com", "edmunds.com", "openauto.com"];

  // Sender domains that are reliably one category regardless of body wording.
  var ALERT_DOMAINS = ["realtor.com", "cars.com", "carfax.com", "imotors.com", "ziprecruiter.com",
    "remotehunter.com", "autotrader.com", "cargurus.com", "indeed.com", "glassdoor.com"];
  var NEWSLETTER_DOMAINS = ["beehiiv.com", "substack.com", "convertkit.com", "kaggle.com",
    "freecodecamp.org", "medium.com", "bytebytego.com"];

  // Social and developer platforms: notifications about the user are alerts;
  // feed posts and article digests are newsletters. Checked before the
  // keyword rules because these mails quote other people's posts.
  var SOCIAL_DOMAINS = ["linkedin.com", "facebookmail.com", "x.com", "twitter.com",
    "instagram.com", "github.com", "gitlab.com", "slack.com", "discord.com"];
  var SOCIAL_FEED = new RegExp(
    "\\b(recently posted|reshared|shared a post|posted:|is popular|trending|" +
    "top (posts|stories)|newsletter|digest|article|edition)\\b");
  var SOCIAL_ALERT = new RegExp(
    "\\b(jobs?|hiring|hired|openings?|applied|application|" +
    "invit(e|ed|ation)s?|you may know|connect(ion)?s?|viewed your|" +
    "appeared in \\d+ searche?s?|mentioned you|tagged you|replied|commented|" +
    "message|follow(ed|er)s?|notifications?|pull request|issue|review|" +
    "build|workflow|security)\\b");

  // em.cars.com matches cars.com; notcars.com does not.
  function matches(domain, domains) {
    return domains.some(function (d) { return domain === d || domain.endsWith("." + d); });
  }

  function socialCategory(email, domain) {
    if (!matches(domain, SOCIAL_DOMAINS)) return null;
    var subject = (email.subject || "").toLowerCase();
    if (SOCIAL_ALERT.test(subject)) return "alert";
    if (SOCIAL_FEED.test(subject) || matches(domain, ["linkedin.com"])) {
      // LinkedIn mail that isn't about the user is feed/news content, but
      // Gmail's Promotions label (sponsored rankings, ads) still wins.
      if ((email.labels || []).indexOf("CATEGORY_PROMOTIONS") !== -1) return null;
      return "newsletter";
    }
    return "alert";
  }

  var MARKETING_SUBDOMAINS = ["marketing", "promo", "promos", "promotions", "offers", "mailer", "deals"];
  // Only phrases a person wouldn't write to a friend; "great deal on the
  // couch" from a friend stays personal.
  var AD_PHRASE_RE = new RegExp(
    "\\b\\d{1,2}% off\\b|promo code|coupon|shop now|limited time|save up to|" +
    "only \\d+ \\w+ left|fees? waived|unsubscribe");

  function looksLikeMarketing(domain, head) {
    var dots = domain.split(".").length - 1;
    var first = dots >= 2 ? domain.split(".")[0] : "";
    return MARKETING_SUBDOMAINS.indexOf(first) !== -1 || AD_PHRASE_RE.test(head);
  }

  // Header/keyword baseline. Returns { category, confidence }.
  function classify(email) {
    var subject = email.subject || "";
    var snippet = email.snippet || "";
    var body = (email.body_text || "").slice(0, 2000);
    var labels = email.labels || [];
    var blob = (subject + "\n" + snippet + "\n" + body).toLowerCase();

    for (var i = 0; i < URGENT_RULES.length; i++) {
      if (new RegExp(URGENT_RULES[i][1]).test(blob)) {
        return { category: URGENT_RULES[i][0], confidence: 0.7 };
      }
    }

    var domain = (email.sender_domain || "").toLowerCase();
    var head = (subject + "\n" + snippet).toLowerCase();
    // Gmail's own category labels are strong evidence when present, but Gmail
    // also files some marketing as Personal; that is treated like the
    // Promotions tab.
    var bulkPersonal = false;
    if (labels.indexOf("CATEGORY_PERSONAL") !== -1) {
      if (!looksLikeMarketing(domain, head)) return { category: "personal", confidence: 0.5 };
      bulkPersonal = true;
    }

    var social = socialCategory(email, domain);
    if (social) return { category: social, confidence: 0.6 };

    // On mail Gmail files as Promotions, bill/subscription words deep in the
    // body are fine print, so those two only count in subject/preview.
    var promoTab = labels.indexOf("CATEGORY_PROMOTIONS") !== -1 || bulkPersonal;
    var listing = matches(domain, LISTING_DOMAINS);
    // Card statements say "payment received" and "next payment" too; those
    // stay bills.
    var chargeText = promoTab ? head : blob;
    if (isRecurringCharge(chargeText) && !new RegExp(BILL_PATTERN).test(chargeText)) {
      return { category: "subscription", confidence: 0.7 };
    }
    for (var j = 0; j < RULES.length; j++) {
      var category = RULES[j][0];
      if (category === "shipping" && listing) continue;
      if (category === "alert" && promoTab) continue;
      var text = promoTab && (category === "bill" || category === "subscription") ? head : blob;
      if (new RegExp(RULES[j][1]).test(text)) return { category: category, confidence: 0.7 };
    }

    if (matches(domain, ALERT_DOMAINS)) return { category: "alert", confidence: 0.55 };
    if (matches(domain, NEWSLETTER_DOMAINS)) return { category: "newsletter", confidence: 0.55 };
    if (promoTab) return { category: "promotion", confidence: 0.6 };

    for (var k = 0; k < NOTICE_RULES.length; k++) {
      if (new RegExp(NOTICE_RULES[k][1]).test(blob)) {
        return { category: NOTICE_RULES[k][0], confidence: 0.5 };
      }
    }

    return { category: "other", confidence: 0.3 };
  }

  // Second-pass split of the broad 'promotion' bucket, so a travel deal is
  // told apart from a clothing sale without opening either.
  var PROMO_SUBCATS = [
    ["travel", "\\b(flights?|hotels?|resorts?|vacations?|booking\\.com|airbnb|itinerary|airfares?)\\b"],
    ["food", "\\b(restaurant|delivery|doordash|uber eats|grubhub|recipe|menu|dining)\\b"],
    ["groceries", "\\b(grocery|groceries|instacart|supermarket|produce)\\b"],
    ["electronics", "\\b(laptop|phone|electronics|headphones|tv|gadget|charger)\\b"],
    ["clothing", "\\b(clothing|apparel|shoes|dress|sneakers|fashion|wardrobe)\\b"],
    ["entertainment", "\\b(movie|concert|streaming|tickets|show|game pass|subscription box)\\b"],
    ["education", "\\b(courses?|bootcamps?|udemy|coursera|certificat\\w*|masterclass|tutorials?|learning)\\b"],
    ["finance", "\\b(credit card|loan|apr|cashback|invest(ment)?|bank(ing)?)\\b"],
    ["shopping", "\\b(shop now|sale|deal|coupon|promo code|discount|% off)\\b"],
  ];

  function promoSubcategory(email) {
    var blob = ((email.subject || "") + "\n" + (email.snippet || "") + "\n" +
      (email.body_text || "").slice(0, 2000)).toLowerCase();
    for (var i = 0; i < PROMO_SUBCATS.length; i++) {
      if (new RegExp(PROMO_SUBCATS[i][1]).test(blob)) return PROMO_SUBCATS[i][0];
    }
    return null;
  }

  InboxIQ.CATEGORIES = CATEGORIES;
  InboxIQ.classify = classify;
  InboxIQ.promoSubcategory = promoSubcategory;
})(typeof self !== "undefined" && self.InboxIQ ? self.InboxIQ
  : (typeof module !== "undefined" ? (module.exports = {}) : (self.InboxIQ = {})));
