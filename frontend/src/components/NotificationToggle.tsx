import { useState, useEffect } from "react";
import { Bell, BellOff, BellRing } from "lucide-react";
import {
  subscribeToPush,
  unsubscribeFromPush,
  isPushSubscribed,
  sendTestPush,
} from "../services/pushNotifications";

const NotificationToggle = () => {
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) {
      setSupported(false);
      return;
    }
    isPushSubscribed().then(setSubscribed);
  }, []);

  const handleToggle = async () => {
    setLoading(true);
    if (subscribed) {
      const ok = await unsubscribeFromPush();
      if (ok) setSubscribed(false);
    } else {
      const ok = await subscribeToPush();
      if (ok) setSubscribed(true);
    }
    setLoading(false);
  };

  const handleTest = async () => {
    setLoading(true);
    await sendTestPush();
    setLoading(false);
  };

  if (!supported) return null;

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleToggle}
        disabled={loading}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          subscribed
            ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
            : "bg-white/5 text-gray-400 border border-white/10 hover:border-indigo-500/30 hover:text-indigo-300"
        } ${loading ? "opacity-50 cursor-wait" : ""}`}
        title={subscribed ? "Notifications enabled" : "Enable notifications"}
      >
        {subscribed ? <Bell size={14} /> : <BellOff size={14} />}
        {subscribed ? "Notifications On" : "Enable Notifications"}
      </button>
      {subscribed && (
        <button
          onClick={handleTest}
          disabled={loading}
          className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-gray-500 hover:text-indigo-300 border border-white/5 hover:border-indigo-500/30 transition-all"
          title="Send test notification"
        >
          <BellRing size={12} />
          Test
        </button>
      )}
    </div>
  );
};

export default NotificationToggle;
