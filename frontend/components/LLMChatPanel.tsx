"use client";

// components/LLMChatPanel.tsx
// LLM Chat panel untuk Cortex page

import { useState, useCallback, useEffect, useRef } from "react";
import type { SSEEvent } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

interface LLMChatPanelProps {
  providerId: string;
  model: string;
  onExplain?: (topic: string) => Promise<void>;
  onReview?: (path: string) => Promise<void>;
  onRefactor?: (nodeName: string) => Promise<void>;
}

interface UseLLMChatReturn {
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  input: string;
  setInput: (input: string) => void;
  loading: boolean;
  sendMessage: () => Promise<void>;
  clearMessages: () => void;
}

export function useLLMChat(providerId: string, model: string): UseLLMChatReturn {
  const [messages, setMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || loading) return;
    
    const userMessage = input.trim();
    setInput("");
    setLoading(true);
    
    const userMsg = { role: "user" as const, content: userMessage };
    setMessages(prev => [...prev, userMsg]);
    
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/llm/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: providerId,
          model,
          messages: [
            { role: "system", content: "You are a helpful AI assistant for code analysis and explanation." },
            { role: "user", content: userMessage }
          ],
          temperature: 0.3,
          max_tokens: 2048,
          stream: true,
        }),
        signal: abortController.signal,
      });
      
      if (!res.ok) {
        let errDetail = `HTTP ${res.status}`;
        try {
          const errJson = await res.json();
          if (errJson.detail) errDetail = errJson.detail;
          else if (errJson.message) errDetail = errJson.message;
        } catch {
          // ignore
        }
        throw new Error(errDetail);
      }
      
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = "";
      let buffer = "";
      
      // Add empty assistant message for streaming
      setMessages(prev => [...prev, { role: "assistant", content: "" }]);
      
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          
          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data: ")) {
              const data = trimmed.slice(6).trim();
              if (data === "[DONE]") continue;
              
              try {
                const parsed = JSON.parse(data);
                const content =
                  parsed.choices?.[0]?.delta?.content ||
                  parsed.message?.content ||
                  parsed.response ||
                  parsed.content ||
                  "";
                if (content) {
                  assistantMessage += content;
                  setMessages(prev => {
                    const newMessages = [...prev];
                    newMessages[newMessages.length - 1] = { 
                      role: "assistant", 
                      content: assistantMessage 
                    };
                    return newMessages;
                  });
                }
              } catch {
                // Ignore parse errors
              }
            }
          }
        }
        
        if (buffer.trim()) {
          const trimmed = buffer.trim();
          if (trimmed.startsWith("data: ")) {
            const data = trimmed.slice(6).trim();
            if (data !== "[DONE]") {
              try {
                const parsed = JSON.parse(data);
                const content =
                  parsed.choices?.[0]?.delta?.content ||
                  parsed.message?.content ||
                  parsed.response ||
                  parsed.content ||
                  "";
                if (content) {
                  assistantMessage += content;
                }
              } catch {
                // ignore
              }
            }
          }
        }
      }
      
      // Final update
      setMessages(prev => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = { 
          role: "assistant", 
          content: assistantMessage 
        };
        return newMessages;
      });
      
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        console.error("LLM chat error:", err);
        setMessages(prev => {
          const newMessages = [...prev];
          newMessages[newMessages.length - 1] = { 
            role: "assistant", 
            content: `Error: ${err.message}` 
          };
          return newMessages;
        });
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  }, [providerId, model, input, loading]);
  
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);
  
  return {
    messages,
    input,
    setInput,
    loading,
    sendMessage,
    clearMessages,
  };
}

export function LLMChatPanel({
  providerId,
  model,
  onExplain,
  onReview,
  onRefactor,
}: LLMChatPanelProps) {
  const { messages, input, setInput, loading, sendMessage, clearMessages } = useLLMChat(providerId, model);
  const [contextFiles, setContextFiles] = useState<string[]>([]);
  
  const handleExplain = useCallback(async () => {
    if (!input.trim()) return;
    await onExplain?.(input);
  }, [input, onExplain]);
  
  const handleReview = useCallback(async () => {
    if (!input.trim()) return;
    await onReview?.(input);
  }, [input, onReview]);
  
  const handleRefactor = useCallback(async () => {
    if (!input.trim()) return;
    await onRefactor?.(input);
  }, [input, onRefactor]);
  
  return (
    <div className="flex flex-col h-full bg-[#0d1117] rounded-xl border border-slate-800/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-purple-500"></span>
          <span className="text-sm font-semibold text-white">LLM Chat</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 border border-purple-500/30 font-bold">
            {model}
          </span>
          <button
            onClick={clearMessages}
            disabled={loading}
            className="text-[10px] px-2 py-1 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 text-xs">
            <svg className="w-12 h-12 text-slate-600 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8a9.863 9.863 0 014.255.949L21 4l-1.395 3.72c-.51.3-.954.924-.851 1.527C19.491 8.486 18 9.553 18 12c0 4.418-4.03 8-9 8z" />
            </svg>
            <p className="text-sm text-slate-400 mt-2">Mulai obrolan dengan LLM</p>
            <p className="text-[10px] text-slate-600 mt-1">Tanyakan tentang kode, minta review, atau minta saran refactor</p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div
                  className={`flex-1 max-w-[85%] p-3 rounded-xl ${
                    msg.role === "user" 
                      ? "bg-blue-600/20 text-blue-100" 
                      : "bg-slate-800/40 text-slate-100"
                  }`}
                >
                  <p className="text-xs whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            ))}
          </div>
        )}
        {loading && (
          <div className="flex items-center gap-2 px-4 py-2 text-xs text-slate-500">
            <div className="animate-spin rounded-full h-3 w-3 border-2 border-purple-500 border-t-transparent" />
            <span>AI sedang mengetik...</span>
          </div>
        )}
      </div>
      
      {/* Input */}
      <div className="p-4 border-t border-slate-800/60">
        <div className="flex gap-2">
          {/* Select provider + model milik ProviderSelect, di atas. Select lama
              dengan model hardcode (gpt-4o, claude-3-5-sonnet) DIHAPUS: ia tidak
              punya onChange, jadi selalu menampilkan "GPT-4o" sementara chat
              sebenarnya mengirim model milik provider yang dipilih user
              (mis. deepseek-chat). Kontradiksi itu yang bikin user mengira
              setting provider-nya tidak dipakai. */}
          <div className="flex-1 flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), sendMessage())}
              placeholder="Tanyakan tentang kode, minta review, atau minta refactor..."
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600"
              disabled={loading}
            />
            <button
              onClick={sendMessage}
              // providerId ikut diperiksa: tanpa itu, Enter/klik Kirim dengan
              // provider yang belum tersinkron (state parent masih "")
              // mengirim provider_id="" dan backend membalas 404
              // "Provider not found or disabled" - error yang tidak
              // memberi tahu user apa yang salah.
              disabled={loading || !input.trim() || !providerId}
              title={
                providerId
                  ? undefined
                  : "Pilih provider LLM di Settings -> LLM dulu. Tanpa provider, chat akan 404."
              }
              className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "..." : "Kirim"}
            </button>
          </div>
        </div>
        
        {/* Quick Actions */}
        <div className="px-4 pb-4 space-y-2 border-t border-slate-800/60 pt-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">Quick Actions</div>
          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={onExplain ? () => onExplain(input) : undefined}
              disabled={loading || !input.trim() || !onExplain}
              className="w-full py-2 rounded-lg bg-blue-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Explain
            </button>
            <button
              onClick={onReview ? () => onReview(input) : undefined}
              disabled={loading || !input.trim() || !onReview}
              className="w-full py-2 rounded-lg bg-purple-600/20 border border-purple-500/30 text-purple-400 hover:bg-purple-600/30 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Review
            </button>
            <button
              onClick={onRefactor ? () => onRefactor(input) : undefined}
              disabled={loading || !input.trim() || !onRefactor}
              className="w-full py-2 rounded-lg bg-amber-600/20 border border-amber-500/30 text-amber-400 hover:bg-amber-600/30 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Refactor
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}