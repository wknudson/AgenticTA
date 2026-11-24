import React, { useState, useRef, useEffect } from 'react';
import { ChevronLeft } from 'lucide-react';
import Logo from './Logo';
import { ChevronDown } from './Icons';
import { ViewState, ClassSummary } from '../types';
import { COLORS } from '../constants';
import ClassTabs from './ClassTabs';

interface LayoutProps {
  children: React.ReactNode;
  currentView: ViewState;
  onViewChange: (view: ViewState) => void;
  onLogout: () => void;
  selectedClass: ClassSummary | null;
  onBackToClasses: () => void;
}

const Layout: React.FC<LayoutProps> = ({ children, currentView, onViewChange, onLogout, selectedClass, onBackToClasses }) => {
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    };
    if (profileOpen) {
      document.addEventListener('click', handleClickOutside);
      return () => document.removeEventListener('click', handleClickOutside);
    }
  }, [profileOpen]);

  const isClassSelect = currentView === 'CLASS_SELECT';

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      {/* Sticky Header & Navigation Wrapper */}
      <div className="sticky top-0 z-50 bg-white shadow-sm">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-4 sm:px-6 lg:px-8 py-2 flex items-center justify-between min-h-0">
          <div className="flex items-center gap-3 sm:gap-4 flex-1 min-w-0">
            <button
              type="button"
              onClick={() => {
                if (selectedClass) {
                  onViewChange('ASSIGNMENT_LIST');
                } else {
                  onBackToClasses();
                }
              }}
              className="flex-shrink-0"
              aria-label="Go to assignments"
            >
              <Logo size="sm" />
            </button>
            <div className="h-6 w-[1px] bg-gray-300 mx-1 flex-shrink-0"></div>
            {!isClassSelect && selectedClass ? (
              // Back to the class list (this used to be the "Classes" tab).
              <button
                type="button"
                onClick={onBackToClasses}
                title="All classes"
                className="group flex items-center gap-1 min-w-0 rounded-lg -ml-1 pl-1 pr-2 py-1 text-gray-600 font-medium hover:text-black hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ba3638]"
              >
                <ChevronLeft className="w-4 h-4 shrink-0 text-gray-400 group-hover:text-black" aria-hidden="true" />
                <span className="sr-only">Back to all classes: </span>
                <span className="truncate">
                  {`${selectedClass.class_name}${selectedClass.semester ? ` · ${selectedClass.semester}` : ''}`}
                </span>
              </button>
            ) : (
              <span className="text-gray-600 font-medium truncate">My Classes</span>
            )}
          </div>

          <div className="relative flex items-center gap-4" ref={profileRef}>
            <button
              type="button"
              onClick={() => setProfileOpen((o) => !o)}
              className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#ba3638]"
              aria-expanded={profileOpen}
              aria-haspopup="true"
            >
              <img
                src="https://picsum.photos/seed/teacher/100"
                alt="Profile"
                className="w-10 h-10 rounded-full border-2 border-gray-200 shadow-sm"
              />
              <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${profileOpen ? 'rotate-180' : ''}`} />
            </button>
            {profileOpen && (
              <div className="absolute right-0 top-full pt-1 z-[100]">
                <div className="w-48 bg-white rounded-xl shadow-xl border border-gray-200 py-1">
                  <button
                    type="button"
                    onClick={() => { setProfileOpen(false); onLogout(); }}
                    className="w-full text-left px-4 py-3 text-sm font-medium transition-colors rounded-lg mx-1 hover:opacity-90"
                    style={{ color: COLORS.primary }}
                  >
                    Logout
                  </button>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Class-level tabs (grouped) — only shown when a class is selected */}
        {!isClassSelect && selectedClass && (
          <ClassTabs classId={selectedClass.class_id} currentView={currentView} onViewChange={onViewChange} />
        )}
      </div>

      {/* Main Content */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full">
        {children}
      </main>
    </div>
  );
};

export default Layout;
