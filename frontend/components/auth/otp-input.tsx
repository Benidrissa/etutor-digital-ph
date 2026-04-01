'use client';

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';

interface OTPInputProps {
  length?: number;
  value?: string;
  onChange?: (value: string) => void;
  onComplete?: (value: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
  className?: string;
  error?: boolean;
}

export interface OTPInputRef {
  focus: () => void;
  clear: () => void;
}

export const OTPInput = forwardRef<OTPInputRef, OTPInputProps>(
  ({ 
    length = 6, 
    value = '', 
    onChange, 
    onComplete,
    disabled = false,
    autoFocus = false,
    placeholder = '',
    className = '',
    error = false
  }, ref) => {
    const t = useTranslations('Auth');
    // Derive digits from value prop directly (controlled component pattern)
    const digits = value.padEnd(length, '').slice(0, length).split('');
    const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

    // Initialize refs array
    useEffect(() => {
      inputRefs.current = inputRefs.current.slice(0, length);
    }, [length]);

    // Auto-focus first input on mount
    useEffect(() => {
      if (autoFocus && inputRefs.current[0] && !disabled) {
        inputRefs.current[0].focus();
      }
    }, [autoFocus, disabled]);

    // Expose methods via ref
    useImperativeHandle(ref, () => ({
      focus: () => {
        const firstEmptyIndex = digits.findIndex(digit => digit === '');
        const targetIndex = firstEmptyIndex === -1 ? length - 1 : firstEmptyIndex;
        inputRefs.current[targetIndex]?.focus();
      },
      clear: () => {
        onChange?.('');
        inputRefs.current[0]?.focus();
      }
    }));

    const handleInputChange = useCallback((index: number, inputValue: string) => {
      // Only allow digits
      const newValue = inputValue.replace(/\D/g, '').slice(0, 1);
      
      const newDigits = [...digits];
      newDigits[index] = newValue;

      const fullValue = newDigits.join('');
      onChange?.(fullValue);

      // Auto-advance to next input
      if (newValue && index < length - 1) {
        inputRefs.current[index + 1]?.focus();
      }

      // Call onComplete when all digits are filled
      if (fullValue.length === length && onComplete) {
        onComplete(fullValue);
      }
    }, [digits, length, onChange, onComplete]);

    const handleKeyDown = useCallback((index: number, event: React.KeyboardEvent) => {
      if (event.key === 'Backspace' || event.key === 'Delete') {
        event.preventDefault();
        
        const newDigits = [...digits];
        
        if (digits[index]) {
          // Clear current digit
          newDigits[index] = '';
        } else if (index > 0) {
          // Move to previous input and clear it
          newDigits[index - 1] = '';
          inputRefs.current[index - 1]?.focus();
        }
        
        onChange?.(newDigits.join(''));
      } else if (event.key === 'ArrowLeft' && index > 0) {
        event.preventDefault();
        inputRefs.current[index - 1]?.focus();
      } else if (event.key === 'ArrowRight' && index < length - 1) {
        event.preventDefault();
        inputRefs.current[index + 1]?.focus();
      }
    }, [digits, length, onChange]);

    const handlePaste = useCallback((event: React.ClipboardEvent) => {
      event.preventDefault();
      
      const pasteData = event.clipboardData.getData('text/plain').replace(/\D/g, '');
      const newDigits = pasteData.padEnd(length, '').slice(0, length).split('');
      
      const fullValue = newDigits.join('');
      onChange?.(fullValue);
      
      // Focus the next empty input or the last input
      const nextEmptyIndex = newDigits.findIndex(digit => digit === '');
      const targetIndex = nextEmptyIndex === -1 ? length - 1 : Math.min(nextEmptyIndex, length - 1);
      inputRefs.current[targetIndex]?.focus();

      // Call onComplete if all digits are filled
      if (fullValue.length === length && onComplete) {
        onComplete(fullValue);
      }
    }, [length, onChange, onComplete]);

    const baseInputClass = `
      w-11 h-11 sm:w-12 sm:h-12 text-center text-lg font-semibold
      border-2 rounded-lg bg-background
      focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2
      transition-colors duration-200
      disabled:cursor-not-allowed disabled:opacity-50
      ${error 
        ? 'border-red-500 text-red-900 focus:border-red-500 focus:ring-red-500' 
        : 'border-input hover:border-gray-400 focus:border-ring'
      }
    `.trim().replace(/\s+/g, ' ');

    return (
      <div className={`flex gap-2 justify-center ${className}`}>
        {digits.map((digit, index) => (
          <input
            key={index}
            ref={(el) => { inputRefs.current[index] = el; }}
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={1}
            value={digit}
            onChange={(e) => handleInputChange(index, e.target.value)}
            onKeyDown={(e) => handleKeyDown(index, e)}
            onPaste={handlePaste}
            disabled={disabled}
            placeholder={placeholder}
            className={baseInputClass}
            aria-label={`${t('otpDigit')} ${index + 1}`}
            data-testid={`otp-input-${index}`}
          />
        ))}
      </div>
    );
  }
);

OTPInput.displayName = 'OTPInput';