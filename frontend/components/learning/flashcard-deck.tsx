'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface FlashcardData {
  id: string;
  card_id: string;
  card_index: number;
  term: string;
  definition_fr: string;
  definition_en: string;
  example_aof: string;
  formula?: string;
  sources_cited: string[];
  review_id: string;
  due_date: string;
  stability: number;
  difficulty: number;
}

interface FlashcardDeckProps {
  cards: FlashcardData[];
  onReview: (cardId: string, reviewId: string, rating: string) => void;
  onSessionComplete: (stats: {
    cardsReviewed: number;
    sessionDuration: number;
    ratings: string[];
  }) => void;
  isLoading?: boolean;
  language: 'fr' | 'en';
}

type Rating = 'again' | 'hard' | 'good' | 'easy';

export function FlashcardDeck({ 
  cards, 
  onReview, 
  onSessionComplete, 
  isLoading = false, 
  language = 'fr' 
}: FlashcardDeckProps) {
  const t = useTranslations('Flashcards');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [sessionStartTime] = useState(Date.now());
  const [reviewedRatings, setReviewedRatings] = useState<string[]>([]);
  const [touchStart, setTouchStart] = useState<{ x: number; y: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [cardTransform, setCardTransform] = useState({ x: 0, rotation: 0 });
  const [pendingRating, setPendingRating] = useState<Rating | null>(null);
  
  const cardRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const currentCard = cards[currentIndex];
  const isLastCard = currentIndex === cards.length - 1;

  // Auto-flip card back to front when advancing to next card
  useEffect(() => {
    setIsFlipped(false);
    setCardTransform({ x: 0, rotation: 0 });
    setPendingRating(null);
  }, [currentIndex]);

  const handleCardFlip = () => {
    setIsFlipped(!isFlipped);
  };

  const handleRating = (rating: Rating) => {
    if (!currentCard) return;

    // Record the review
    onReview(currentCard.id, currentCard.review_id, rating);
    
    const newRatings = [...reviewedRatings, rating];
    setReviewedRatings(newRatings);

    if (isLastCard) {
      // Complete the session
      const sessionDuration = Math.floor((Date.now() - sessionStartTime) / 1000);
      onSessionComplete({
        cardsReviewed: cards.length,
        sessionDuration,
        ratings: newRatings,
      });
    } else {
      // Advance to next card
      setCurrentIndex(prev => prev + 1);
    }
  };

  // Touch/swipe gesture handling
  const handleTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    setTouchStart({ x: touch.clientX, y: touch.clientY });
    setIsDragging(true);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!touchStart || !isDragging) return;
    
    const touch = e.touches[0];
    const deltaX = touch.clientX - touchStart.x;
    const deltaY = Math.abs(touch.clientY - touchStart.y);
    
    // Only track horizontal swipes (ignore vertical scrolling)
    if (deltaY > 50) return;
    
    // Calculate rotation based on horizontal movement
    const maxDelta = 150;
    const rotation = Math.max(-15, Math.min(15, (deltaX / maxDelta) * 15));
    
    setCardTransform({ x: deltaX, rotation });

    // Visual feedback for rating zones
    if (Math.abs(deltaX) > 50) {
      if (deltaX < -100) setPendingRating('again');
      else if (deltaX < -50) setPendingRating('hard');
      else if (deltaX > 100) setPendingRating('easy');
      else if (deltaX > 50) setPendingRating('good');
    } else {
      setPendingRating(null);
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!touchStart || !isDragging) return;
    
    const touch = e.changedTouches[0];
    const deltaX = touch.clientX - touchStart.x;
    
    setIsDragging(false);
    setTouchStart(null);

    // Determine if swipe was strong enough to trigger rating
    if (Math.abs(deltaX) > 80 && isFlipped) {
      if (deltaX < -100) handleRating('again');
      else if (deltaX < -40) handleRating('hard');
      else if (deltaX > 100) handleRating('easy');
      else if (deltaX > 40) handleRating('good');
    } else {
      // Snap back to center
      setCardTransform({ x: 0, rotation: 0 });
      setPendingRating(null);
    }
  };

  // Mouse event handlers for desktop
  const handleMouseDown = (e: React.MouseEvent) => {
    setTouchStart({ x: e.clientX, y: e.clientY });
    setIsDragging(true);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!touchStart || !isDragging) return;
    
    const deltaX = e.clientX - touchStart.x;
    const deltaY = Math.abs(e.clientY - touchStart.y);
    
    if (deltaY > 50) return;
    
    const maxDelta = 150;
    const rotation = Math.max(-15, Math.min(15, (deltaX / maxDelta) * 15));
    
    setCardTransform({ x: deltaX, rotation });

    if (Math.abs(deltaX) > 50) {
      if (deltaX < -100) setPendingRating('again');
      else if (deltaX < -50) setPendingRating('hard');
      else if (deltaX > 100) setPendingRating('easy');
      else if (deltaX > 50) setPendingRating('good');
    } else {
      setPendingRating(null);
    }
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!touchStart || !isDragging) return;
    
    const deltaX = e.clientX - touchStart.x;
    
    setIsDragging(false);
    setTouchStart(null);

    if (Math.abs(deltaX) > 80 && isFlipped) {
      if (deltaX < -100) handleRating('again');
      else if (deltaX < -40) handleRating('hard');
      else if (deltaX > 100) handleRating('easy');
      else if (deltaX > 40) handleRating('good');
    } else {
      setCardTransform({ x: 0, rotation: 0 });
      setPendingRating(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-pulse mb-4">
            <div className="w-80 h-96 bg-gray-200 rounded-xl mx-auto"></div>
          </div>
          <p className="text-muted-foreground">{t('loading')}</p>
        </div>
      </div>
    );
  }

  if (!cards.length) {
    return (
      <div className="text-center py-12">
        <div className="text-6xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold mb-2">{t('noCardsToday')}</h2>
        <p className="text-muted-foreground">{t('wellDone')}</p>
      </div>
    );
  }

  if (!currentCard) return null;

  return (
    <div className="max-w-md mx-auto px-4" ref={containerRef}>
      {/* Progress indicator */}
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm text-muted-foreground">
            {t('cardCount', { current: currentIndex + 1, total: cards.length })}
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div 
            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
            style={{ width: `${((currentIndex + 1) / cards.length) * 100}%` }}
          />
        </div>
      </div>

      {/* Swipe direction indicators */}
      {isFlipped && (
        <div className="flex justify-between items-center mb-4 text-xs text-muted-foreground">
          <div className={cn(
            "flex items-center space-x-1 px-2 py-1 rounded",
            pendingRating === 'again' && "bg-red-100 text-red-700"
          )}>
            <span>← {t('again')}</span>
          </div>
          <div className={cn(
            "flex items-center space-x-1 px-2 py-1 rounded",
            pendingRating === 'hard' && "bg-orange-100 text-orange-700"
          )}>
            <span>← {t('hard')}</span>
          </div>
          <div className={cn(
            "flex items-center space-x-1 px-2 py-1 rounded",
            pendingRating === 'good' && "bg-green-100 text-green-700"
          )}>
            <span>{t('good')} →</span>
          </div>
          <div className={cn(
            "flex items-center space-x-1 px-2 py-1 rounded",
            pendingRating === 'easy' && "bg-blue-100 text-blue-700"
          )}>
            <span>{t('easy')} →</span>
          </div>
        </div>
      )}

      {/* Flashcard */}
      <div className="relative mb-6">
        <Card 
          ref={cardRef}
          className={cn(
            "w-full h-96 cursor-pointer transition-all duration-300",
            "shadow-lg hover:shadow-xl",
            isDragging && "transition-none"
          )}
          style={{
            transform: `translateX(${cardTransform.x}px) rotate(${cardTransform.rotation}deg)`,
          }}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          onMouseDown={handleMouseDown}
          onMouseMove={isDragging ? handleMouseMove : undefined}
          onMouseUp={handleMouseUp}
          onMouseLeave={isDragging ? handleMouseUp : undefined}
          onClick={!isDragging ? handleCardFlip : undefined}
        >
          <CardContent className="h-full flex flex-col justify-center p-6">
            <div className={cn(
              "flip-card-inner h-full relative",
              isFlipped && "flipped"
            )}>
              {/* Front of card */}
              <div className="flip-card-front absolute inset-0 flex flex-col justify-center items-center text-center">
                <h3 className="text-2xl font-bold mb-4">{currentCard.term}</h3>
                {!isFlipped && (
                  <p className="text-muted-foreground text-sm">{t('tapToReveal')}</p>
                )}
              </div>

              {/* Back of card */}
              <div className="flip-card-back absolute inset-0 flex flex-col justify-start p-4 space-y-4">
                <div>
                  <h4 className="font-semibold text-lg mb-2">{t('definition')}</h4>
                  <p className="text-sm mb-3">
                    {language === 'fr' ? currentCard.definition_fr : currentCard.definition_en}
                  </p>
                </div>

                {currentCard.example_aof && (
                  <div>
                    <h4 className="font-semibold mb-1">{t('example')}</h4>
                    <p className="text-sm text-muted-foreground mb-3">
                      {currentCard.example_aof}
                    </p>
                  </div>
                )}

                {currentCard.formula && (
                  <div>
                    <h4 className="font-semibold mb-1">{t('formula')}</h4>
                    <p className="text-sm font-mono bg-gray-50 p-2 rounded">
                      {currentCard.formula}
                    </p>
                  </div>
                )}

                {currentCard.sources_cited.length > 0 && (
                  <div className="mt-auto">
                    <p className="text-xs text-muted-foreground">
                      {t('source', { source: currentCard.sources_cited[0] })}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Rating buttons (shown only when card is flipped) */}
      {isFlipped && (
        <div className="space-y-4">
          <p className="text-center text-sm text-muted-foreground">
            {t('swipeInstructions')}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Button
              variant="outline"
              className="min-h-11 bg-red-50 border-red-200 hover:bg-red-100 text-red-700"
              onClick={() => handleRating('again')}
            >
              <div className="text-center">
                <div className="font-semibold">{t('again')}</div>
                <div className="text-xs opacity-75">{t('ratingDescription.again')}</div>
              </div>
            </Button>
            
            <Button
              variant="outline"
              className="min-h-11 bg-orange-50 border-orange-200 hover:bg-orange-100 text-orange-700"
              onClick={() => handleRating('hard')}
            >
              <div className="text-center">
                <div className="font-semibold">{t('hard')}</div>
                <div className="text-xs opacity-75">{t('ratingDescription.hard')}</div>
              </div>
            </Button>
            
            <Button
              variant="outline"
              className="min-h-11 bg-green-50 border-green-200 hover:bg-green-100 text-green-700"
              onClick={() => handleRating('good')}
            >
              <div className="text-center">
                <div className="font-semibold">{t('good')}</div>
                <div className="text-xs opacity-75">{t('ratingDescription.good')}</div>
              </div>
            </Button>
            
            <Button
              variant="outline"
              className="min-h-11 bg-blue-50 border-blue-200 hover:bg-blue-100 text-blue-700"
              onClick={() => handleRating('easy')}
            >
              <div className="text-center">
                <div className="font-semibold">{t('easy')}</div>
                <div className="text-xs opacity-75">{t('ratingDescription.easy')}</div>
              </div>
            </Button>
          </div>
        </div>
      )}

      {/* Card flip prompt (shown only when card is not flipped) */}
      {!isFlipped && (
        <div className="text-center">
          <Button 
            variant="default"
            size="lg"
            onClick={handleCardFlip}
            className="min-h-11 px-8"
          >
            {t('showAnswer')}
          </Button>
        </div>
      )}

      <style jsx>{`
        .flip-card-inner {
          position: relative;
          width: 100%;
          height: 100%;
          text-align: center;
          transition: transform 0.3s;
          transform-style: preserve-3d;
        }

        .flip-card-inner.flipped {
          transform: rotateY(180deg);
        }

        .flip-card-front, .flip-card-back {
          position: absolute;
          width: 100%;
          height: 100%;
          -webkit-backface-visibility: hidden;
          backface-visibility: hidden;
        }

        .flip-card-back {
          transform: rotateY(180deg);
        }
      `}</style>
    </div>
  );
}