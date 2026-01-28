import { motion } from 'framer-motion'

function Loader() {
  return (
    <div className="fixed inset-0 bg-slate-900/80 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="text-center">
        <motion.div
          className="relative w-24 h-24 mx-auto mb-6"
        >
          {[...Array(3)].map((_, i) => (
            <motion.div
              key={i}
              className="absolute inset-0 border-4 border-transparent border-t-purple-500 rounded-full"
              animate={{
                rotate: 360,
                scale: [1, 1.1, 1],
              }}
              transition={{
                rotate: {
                  duration: 1.5,
                  repeat: Infinity,
                  ease: "linear",
                  delay: i * 0.2,
                },
                scale: {
                  duration: 1.5,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: i * 0.2,
                },
              }}
              style={{
                width: `${24 - i * 4}rem`,
                height: `${24 - i * 4}rem`,
                top: `${i * 2}rem`,
                left: `${i * 2}rem`,
              }}
            />
          ))}
        </motion.div>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="text-xl font-medium text-white"
        >
          Анализируем сайт...
        </motion.p>
      </div>
    </div>
  )
}

export default Loader
