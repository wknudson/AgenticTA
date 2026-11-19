/**
 * LLM client for the Express API (assignment generation, tutor chat, short-answer grading).
 *
 * The app used to call Groq, which is not an allowed provider for the course project.
 * It now calls OpenAI directly. The Python agents service picks its own models per
 * agent in agents/config.yaml; this file only covers the original Express features.
 *
 *   OPENAI_API_KEY   required for these AI endpoints
 *   EXPRESS_AI_MODEL optional, defaults to gpt-6.2-sol
 */
import dotenv from 'dotenv';
import OpenAI from 'openai';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(here, '..', '..', '.env') });

export const llm: OpenAI | null = process.env.OPENAI_API_KEY
  ? new OpenAI({ apiKey: process.env.OPENAI_API_KEY })
  : null;

export const LLM_MODEL = process.env.EXPRESS_AI_MODEL || 'gpt-6.2-sol';

export const LLM_NOT_CONFIGURED = 'AI is not configured. Set OPENAI_API_KEY in .env.';
